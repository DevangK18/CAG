"""
ManifestIngestionService: Load Excel manifest and download CAG PDF reports.

PHASE 3 FIX IMPLEMENTED:
- Proper metadata extraction from all Excel columns
- Report_No format conversion: "2025/15" → "15 of 2025"
- Department mapping to full Ministry names
- Report Type expansion to full names
- Date formatting standardization

FILE NAMING UPDATE:
- Reports now saved as: {Report_No}_{Recommended Title}.pdf
- Example: 2017_10_Performance_Audit_of_Union_Government_Schemes_for_Flood_Control.pdf
"""

import logging
import pandas as pd
import httpx
import re
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import List, Literal, Optional, Any, Dict
from src.core.data_contracts import DocumentTask
from src.parsing_pipeline.instrumentation import get_noop_emitter

logger = logging.getLogger(__name__)

# State code lookup for report ID generation
STATE_CODES = {
    "Andhra Pradesh": "AP",
    "Arunachal Pradesh": "AR",
    "Assam": "AS",
    "Bihar": "BR",
    "Chhattisgarh": "CG",
    "Goa": "GA",
    "Gujarat": "GJ",
    "Haryana": "HR",
    "Himachal Pradesh": "HP",
    "Jharkhand": "JH",
    "Karnataka": "KA",
    "Kerala": "KL",
    "Madhya Pradesh": "MP",
    "Maharashtra": "MH",
    "Manipur": "MN",
    "Meghalaya": "ML",
    "Mizoram": "MZ",
    "Nagaland": "NL",
    "Odisha": "OD",
    "Punjab": "PB",
    "Rajasthan": "RJ",
    "Sikkim": "SK",
    "Tamil Nadu": "TN",
    "Telangana": "TS",
    "Tripura": "TR",
    "Uttarakhand": "UK",
    "Uttar Pradesh": "UP",
    "West Bengal": "WB",
    # Union Territories
    "Delhi": "DL",
    "Jammu and Kashmir": "JK",
    "Ladakh": "LA",
    "Puducherry": "PY",
    "Chandigarh": "CH",
    "Andaman and Nicobar Islands": "AN",
    "Dadra and Nagar Haveli and Daman and Diu": "DD",
    "Lakshadweep": "LD",
}

# State name misspelling corrections
STATE_NAME_CORRECTIONS = {
    "Maharastra": "Maharashtra",
    "Maharasthra": "Maharashtra",
    "Gujrat": "Gujarat",
    "Orrisa": "Odisha",
    "Orissa": "Odisha",
    "Chattisgarh": "Chhattisgarh",
    "Chhatisgarh": "Chhattisgarh",
    "Uttrakhand": "Uttarakhand",
    "Uttarkhand": "Uttarakhand",
    "Tamilnadu": "Tamil Nadu",
    "Tamil nadu": "Tamil Nadu",
    "Andhrapradesh": "Andhra Pradesh",
    "Andhra pradesh": "Andhra Pradesh",
    "Madhyapradesh": "Madhya Pradesh",
    "Madhya pradesh": "Madhya Pradesh",
    "Himachalpradesh": "Himachal Pradesh",
    "Himachal pradesh": "Himachal Pradesh",
    "Arunachalpradesh": "Arunachal Pradesh",
    "Arunachal pradesh": "Arunachal Pradesh",
    "Westbengal": "West Bengal",
    "West bengal": "West Bengal",
    "Uttarpradesh": "Uttar Pradesh",
    "Uttar pradesh": "Uttar Pradesh",
}

# Government body type literals
GovernmentBodyType = Literal["union", "state", "local_body"]

# Audit category literals
AuditCategory = Literal["compliance", "performance", "financial", "revenue", "commercial", "atir"]


def detect_government_body_type(manifest_path: str) -> GovernmentBodyType:
    """
    Detect government body type from manifest filename.

    Patterns:
    - "CAG_Union_Reports" or legacy names → "union"
    - "CAG_State_Reports" or "State_Examples" → "state"
    - "CAG_Local_Body_Reports" or "Local_Examples" → "local_body"

    Args:
        manifest_path: Path to the manifest Excel file

    Returns:
        Government body type: "union", "state", or "local_body"
    """
    filename = Path(manifest_path).stem.lower()

    # Check for local body patterns first (more specific)
    if "local_body" in filename or "local-body" in filename or "localbody" in filename:
        return "local_body"
    # "local" without "state" = local_body (catches "Local_Examples")
    elif "local" in filename and "state" not in filename:
        return "local_body"
    elif "state" in filename and "union" not in filename:
        return "state"
    else:
        # Default to union for legacy filenames and explicit union manifests
        return "union"


def infer_audit_category_from_report_type(report_type: str) -> AuditCategory:
    """
    Infer audit_category from Union report_type field.

    Args:
        report_type: Report type string (e.g., "Performance Audit", "Compliance Audit")

    Returns:
        Audit category
    """
    report_type_lower = report_type.lower() if report_type else ""

    if "performance" in report_type_lower:
        return "performance"
    elif "compliance" in report_type_lower:
        return "compliance"
    elif "financial" in report_type_lower or "frbm" in report_type_lower:
        return "financial"
    elif "revenue" in report_type_lower:
        return "revenue"
    elif "commercial" in report_type_lower or "pse" in report_type_lower:
        return "commercial"
    else:
        return "compliance"  # Default


class ManifestIngestionService:
    """
    Service to load CAG manifest Excel file and download PDF reports.

    PHASE 3 FIX: Now extracts ALL metadata from Excel columns and
    standardizes field names for downstream services.

    MULTI-TIER SUPPORT: Handles Union, State, and Local Body reports.
    - Tier detection from manifest filename or explicit column
    - State-prefixed report IDs for State/Local reports
    - Separate storage directories per tier

    FILE NAMING: Reports saved as {Report_No}_{Recommended_Title}.pdf
    """

    def __init__(self, raw_data_dir: str = "data/raw", trace_emitter=None):
        self.base_raw_data_dir = Path(raw_data_dir)
        self.raw_data_dir = self.base_raw_data_dir
        self.base_raw_data_dir.mkdir(parents=True, exist_ok=True)

        # Multi-tier state (set during load_manifest)
        self.government_body_type: GovernmentBodyType = "union"
        self.current_state_name: Optional[str] = None
        self._trace_emitter = trace_emitter or get_noop_emitter()

    def load_manifest(self, manifest_path: str) -> pd.DataFrame:
        """
        Load the Excel manifest, validate columns, and standardize field names.

        PHASE 3 FIX: Comprehensive column mapping and metadata cleaning.
        MULTI-TIER: Detects tier from filename, handles State/Local columns.

        Args:
            manifest_path: Path to CAG manifest Excel file

        Returns:
            DataFrame with standardized column names

        Raises:
            ValueError: If required columns are missing
        """
        try:
            # Detect government body type from filename first
            filename = Path(manifest_path).stem.lower()
            self.government_body_type = detect_government_body_type(manifest_path)
            logger.info(f"Detected government body type: {self.government_body_type}")

            # Trace: Tier detection decision
            self._trace_emitter.emit_decision(
                "1",
                "tier_detection",
                self.government_body_type,
                ["union", "state", "local_body"],
                f"Detected from filename pattern: {filename}",
            )

            # Set tier-specific raw data directory (all tiers use subdirectories)
            self.raw_data_dir = self.base_raw_data_dir / self.government_body_type
            self.raw_data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"PDF storage directory: {self.raw_data_dir}")

            # Auto-detect header row: try header=1 first (original CAG format with title row),
            # fall back to header=0 if columns don't look like headers
            df = pd.read_excel(manifest_path, header=1)

            # Check if we got actual column names by looking for known header patterns
            known_headers = {"SL NO", "Report PDF", "Title", "Original Title", "Date", "Report_No", "State Name", "Audit Category"}
            found_headers = set(str(c).strip() for c in df.columns) & known_headers

            if not found_headers:
                # Columns look like data values, try header=0 instead
                df = pd.read_excel(manifest_path, header=0)
                logger.info(f"Loaded manifest with {len(df)} rows (headers in row 1)")
            else:
                logger.info(f"Loaded manifest with {len(df)} rows (headers in row 2)")

            logger.debug(f"Raw columns: {list(df.columns)}")

            # Strip whitespace from column names
            df.columns = [str(c).strip() if isinstance(c, str) else c for c in df.columns]

            # Comprehensive column mapping: Excel name → Standardized name
            column_mapping = {
                # Required columns
                "SL NO": "SL NO",
                "Report PDF": "Report PDF",
                # Title columns
                "Original Title": "Title",
                "Recommended Title": "Recommended Title",
                # Metadata columns - CRITICAL MAPPING
                "Report_No": "Report No",
                "Report No": "Report No",
                "Union Department": "Ministry",  # Union uses Ministry
                "Ministry": "Ministry",
                "Report Type": "Report Type",
                "Sector": "Sector",
                "Date": "Date",
                "Government Type": "Government Body Type",
                "Government Body Type": "Government Body Type",
                # Multi-tier columns (State/Local)
                "State Name": "State Name",
                "State": "State Name",
                "State_code": "State Code",  # 2-letter state code column
                "State Code": "State Code",
                "Department": "Department",  # State/Local department (different from Union Ministry)
                "Audit Category": "Audit Category",
                "Report Subtype": "Report Subtype",
            }

            # Apply column mapping (only for columns that exist)
            rename_map = {k: v for k, v in column_mapping.items() if k in df.columns}
            df.rename(columns=rename_map, inplace=True)

            # Check for explicit Government Body Type column override
            if "Government Body Type" in df.columns:
                first_value = df["Government Body Type"].dropna().iloc[0] if len(df["Government Body Type"].dropna()) > 0 else None
                if first_value:
                    explicit_type = str(first_value).lower().strip().replace(" ", "_")
                    if explicit_type in ("union", "state", "local_body"):
                        prev_type = self.government_body_type
                        self.government_body_type = explicit_type
                        logger.info(f"Government body type overridden by column: {self.government_body_type}")

                        # Trace: Tier override by column
                        self._trace_emitter.emit_decision(
                            "1",
                            "tier_override",
                            explicit_type,
                            ["union", "state", "local_body"],
                            f"Overridden by manifest column (was: {prev_type})",
                        )

            logger.debug(f"Standardized columns: {list(df.columns)}")

            # Validate required columns
            required_columns = ["SL NO", "Report PDF", "Title"]
            missing = [col for col in required_columns if col not in df.columns]
            if missing:
                raise ValueError(f"Missing required columns: {missing}")

            # Validate State/Local required columns
            if self.government_body_type in ("state", "local_body"):
                if "State Name" not in df.columns:
                    logger.warning("State Name column missing for State/Local manifest. Will use 'Unknown'.")

            # Clean and standardize metadata values
            df = self._clean_metadata(df)

            # Drop empty rows
            df = df.dropna(how="all").dropna(subset=["SL NO"])

            # Log metadata availability
            metadata_cols = ["Report No", "Ministry", "Department", "Report Type", "Sector", "Date", "State Name", "Audit Category"]
            available = [col for col in metadata_cols if col in df.columns]
            logger.info(f"Metadata columns available: {available}")

            # Log sample of cleaned metadata
            if len(df) > 0:
                sample = df.iloc[0]
                if self.government_body_type == "union":
                    logger.debug(
                        f"Sample metadata: Report No='{sample.get('Report No', 'N/A')}', "
                        f"Ministry='{sample.get('Ministry', 'N/A')}', "
                        f"Type='{sample.get('Report Type', 'N/A')}'"
                    )
                else:
                    logger.debug(
                        f"Sample metadata: Report No='{sample.get('Report No', 'N/A')}', "
                        f"State='{sample.get('State Name', 'N/A')}', "
                        f"Dept='{sample.get('Department', 'N/A')}', "
                        f"Category='{sample.get('Audit Category', 'N/A')}'"
                    )

            return df

        except Exception as e:
            raise ValueError(f"Failed to load manifest: {str(e)}")

    def _clean_metadata(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and standardize metadata values.

        PHASE 3 FIX: Comprehensive metadata transformation.
        MULTI-TIER: Handles State Name, Audit Category, Report Subtype.

        Transformations:
        - Report_No: "2025/15" → "15 of 2025"
        - Report Type: "Performance" → "Performance Audit"
        - Ministry: "Railways" → "Ministry of Railways" (Union only)
        - Date: datetime → "YYYY-MM-DD" string
        - State Name: Normalize capitalization
        - Audit Category: Normalize to lowercase
        """
        # Clean Report No: normalize to "X of YYYY" format
        # Handles: "2025/15", "15/2025", "2017_10", "02_2024", etc.
        if "Report No" in df.columns:

            def format_report_no(val):
                if pd.isna(val):
                    return None  # Return None instead of "Unknown" for cleaner downstream handling
                val = str(val).strip()

                if not val or val == "-":
                    return None

                # Handle "Report No. 15 of 2025" format (already correct)
                if "of" in val.lower():
                    return val

                # Handle slash formats: "2025/15" or "15/2025"
                if "/" in val:
                    parts = val.split("/")
                    if len(parts) == 2:
                        first, second = parts
                        # year_num format: "2025/15"
                        if first.isdigit() and len(first) == 4:
                            return f"{second} of {first}"
                        # num_year format: "15/2025"
                        elif second.isdigit() and len(second) == 4:
                            return f"{first} of {second}"

                # Handle underscore formats: "2017_10" or "02_2024"
                if "_" in val:
                    parts = val.split("_")
                    if len(parts) == 2:
                        first, second = parts
                        # year_num format: "2017_10"
                        if first.isdigit() and len(first) == 4:
                            return f"{second} of {first}"
                        # num_year format: "02_2024"
                        elif second.isdigit() and len(second) == 4:
                            return f"{first} of {second}"

                return val

            df["Report No"] = df["Report No"].apply(format_report_no)

        # Expand Report Type to full name
        if "Report Type" in df.columns:
            report_type_mapping = {
                "Performance": "Performance Audit",
                "Compliance": "Compliance Audit",
                "Financial": "Financial Audit",
                "FRBM": "FRBM Compliance Audit",
                "Revenue": "Revenue Audit",
                "Expenditure": "Expenditure Audit",
            }

            def expand_report_type(val):
                if pd.isna(val):
                    return "Unknown"
                val_str = str(val).strip()
                return report_type_mapping.get(val_str, val_str)

            df["Report Type"] = df["Report Type"].apply(expand_report_type)

        # Map Ministry codes to full names (Union reports only)
        if "Ministry" in df.columns:
            ministry_mapping = {
                "Railways": "Ministry of Railways",
                "Civil": "Union Government (Civil)",
                "Defence": "Ministry of Defence",
                "Revenue": "Department of Revenue",
                "Finance": "Ministry of Finance",
                "Economic Affairs": "Department of Economic Affairs",
                "Communications": "Ministry of Communications",
                "Posts": "Department of Posts",
                "Telecom": "Department of Telecommunications",
                "Agriculture": "Ministry of Agriculture",
                "Health": "Ministry of Health & Family Welfare",
                "Education": "Ministry of Education",
                "Environment": "Ministry of Environment, Forest and Climate Change",
                "Power": "Ministry of Power",
                "Renewable Energy": "Ministry of New and Renewable Energy",
                "Science": "Ministry of Science and Technology",
            }

            def expand_ministry(val):
                if pd.isna(val):
                    return "Unknown"
                val_str = str(val).strip()
                # Handle "-" placeholder
                if val_str == "-" or val_str == "":
                    return "Unknown"
                return ministry_mapping.get(val_str, val_str)

            df["Ministry"] = df["Ministry"].apply(expand_ministry)

        # Clean Department for State/Local reports (don't map, just clean)
        if "Department" in df.columns:

            def clean_department(val):
                if pd.isna(val):
                    return None  # None for State/Local, not "Unknown"
                val_str = str(val).strip()
                if val_str == "-" or val_str == "":
                    return None
                return val_str

            df["Department"] = df["Department"].apply(clean_department)

        # Clean State Name
        if "State Name" in df.columns:
            # Track corrections for tracing
            state_corrections: List[Dict[str, str]] = []

            def clean_state_name(val):
                if pd.isna(val):
                    return None
                val_str = str(val).strip()
                if val_str == "-" or val_str == "":
                    return None
                # Title case normalization
                val_str = val_str.title()
                # Apply misspelling corrections
                corrected = STATE_NAME_CORRECTIONS.get(val_str, val_str)
                if corrected != val_str:
                    state_corrections.append({"raw": val_str, "corrected": corrected})
                return corrected

            df["State Name"] = df["State Name"].apply(clean_state_name)

            # Trace: State name corrections applied
            if state_corrections:
                self._trace_emitter.emit_sample("1", "state_name_corrections", state_corrections[:5])

        # Clean Audit Category
        if "Audit Category" in df.columns:

            def clean_audit_category(val):
                if pd.isna(val):
                    return "compliance"  # Default
                val_str = str(val).strip().lower()
                if val_str == "-" or val_str == "":
                    return "compliance"
                # Normalize known values
                category_mapping = {
                    "compliance": "compliance",
                    "performance": "performance",
                    "financial": "financial",
                    "revenue": "revenue",
                    "commercial": "commercial",
                    "atir": "atir",
                    "pse": "commercial",  # PSE maps to commercial
                }
                return category_mapping.get(val_str, val_str)

            df["Audit Category"] = df["Audit Category"].apply(clean_audit_category)

        # Clean Report Subtype
        if "Report Subtype" in df.columns:

            def clean_report_subtype(val):
                if pd.isna(val):
                    return None
                val_str = str(val).strip()
                if val_str == "-" or val_str == "":
                    return None
                # Normalize known values
                subtype_mapping = {
                    "pse": "PSE",
                    "revenue": "Revenue",
                    "pri_ulb": "PRI_ULB",
                    "pri": "PRI_ULB",
                    "ulb": "PRI_ULB",
                }
                return subtype_mapping.get(val_str.lower(), val_str)

            df["Report Subtype"] = df["Report Subtype"].apply(clean_report_subtype)

        # Format dates consistently
        if "Date" in df.columns:

            def format_date(val):
                if pd.isna(val):
                    return "Unknown"
                try:
                    # Try to parse as datetime and format
                    dt = pd.to_datetime(val, errors="coerce")
                    if pd.notna(dt):
                        return dt.strftime("%Y-%m-%d")
                    return str(val)
                except:
                    return str(val)

            df["Date"] = df["Date"].apply(format_date)

        # Fill NaN values with "Unknown" for required metadata columns
        # Note: "Report No" is NOT included - None/null is valid for reports without numbers
        required_metadata_cols = ["Report Type", "Sector"]
        for col in required_metadata_cols:
            if col in df.columns:
                df[col] = df[col].fillna("Unknown")
                df[col] = df[col].replace("", "Unknown")

        # Ministry is required for Union
        if "Ministry" in df.columns:
            df["Ministry"] = df["Ministry"].fillna("Unknown")
            df["Ministry"] = df["Ministry"].replace("", "Unknown")

        return df

    def _sanitize_filename(self, title: str, max_length: int = 80) -> str:
        """
        Sanitize the title to create a safe filename.

        Args:
            title: Raw title string
            max_length: Maximum length for the sanitized string

        Returns:
            Safe filename string
        """
        import unicodedata

        # Normalize to remove accents
        sanitized = (
            unicodedata.normalize("NFKD", title)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        # Remove non alphanumeric except spaces, replace spaces with underscores, strip
        sanitized = (
            re.sub(r"[^a-zA-Z0-9\s]", "", sanitized).replace(" ", "_").strip("_")
        )
        # Truncate to max length
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length].rstrip("_")
        return sanitized

    def _build_metadata(self, row: pd.Series, title: str) -> dict:
        """
        Build complete metadata dict with multi-tier support.

        Args:
            row: DataFrame row with report metadata
            title: Report title

        Returns:
            Metadata dict with all fields including multi-tier fields
        """
        def safe_get(key, default="Unknown"):
            """Safely get value from row, handling NaN."""
            val = row.get(key)
            if pd.isna(val) or val == "":
                return default
            return str(val).strip()

        def safe_get_optional(key):
            """Safely get optional value, returning None for missing/empty."""
            val = row.get(key)
            if pd.isna(val) or val == "" or val == "-":
                return None
            return str(val).strip()

        # Base metadata (all tiers)
        metadata = {
            # Required fields
            "SL NO": row.get("SL NO"),
            "Title": title,
            "Recommended Title": safe_get("Recommended Title", ""),
            # Common metadata fields
            # Report No can be None for reports without numbers (use safe_get_optional)
            "Report No": safe_get_optional("Report No"),
            "Report Type": safe_get("Report Type"),
            "Sector": safe_get("Sector"),
            "Date": safe_get("Date"),
            # Multi-tier fields
            "government_body_type": self.government_body_type,
        }

        # Tier-specific fields
        if self.government_body_type == "union":
            # Union reports use Ministry, not Department
            metadata["Ministry"] = safe_get("Ministry")
            # Backward compatibility: also set Department to Ministry value
            metadata["Department"] = metadata["Ministry"]
            # Infer audit_category from Report Type for Union
            metadata["audit_category"] = infer_audit_category_from_report_type(
                metadata["Report Type"]
            )
            metadata["state_name"] = None
            metadata["department"] = None  # Lowercase for multi-tier field
            metadata["report_subtype"] = None
        else:
            # State/Local Body reports
            state_name = safe_get_optional("State Name")
            metadata["state_name"] = state_name
            metadata["department"] = safe_get_optional("Department")
            # BUG FIX 2: Infer audit_category from Report Type if Audit Category column is missing
            audit_category_val = safe_get_optional("Audit Category")
            if audit_category_val:
                metadata["audit_category"] = audit_category_val.lower()
            else:
                # Infer from Report Type (same as Union logic)
                metadata["audit_category"] = infer_audit_category_from_report_type(
                    metadata["Report Type"]
                )
            metadata["report_subtype"] = safe_get_optional("Report Subtype")
            # Set Ministry to state name for compatibility
            metadata["Ministry"] = state_name or "Unknown"
            metadata["Department"] = metadata["department"] or "Unknown"

        return metadata

    def _build_report_id(self, row: pd.Series) -> str:
        """
        Build report ID from Report_No and Recommended Title.

        Formats by tier:
        - Union: {year}_{serial}_{sanitized_title}
          Example: 2017_10_Performance_Audit_of_Union_Government_Schemes_for_Flood_Control
        - State with report no: {ST}_{year}_{no}_{sanitized_title}
          Example: OD_2025_05_School_Education_Odisha
        - State without report no: {ST}_{year}_{sanitized_title}
        - Local Body ATIR: {ST}_ATIR_{year_range}_{sanitized_title}
          Example: MH_ATIR_2019_Local_Bodies_Maharashtra
        - Local Body with report no: {ST}_{year}_{no}_{sanitized_title}

        Args:
            row: DataFrame row with report metadata

        Returns:
            Sanitized report ID string
        """
        # Get state code for State/Local reports
        state_code = None
        if self.government_body_type in ("state", "local_body"):
            # BUG FIX 1: First check for explicit State Code column
            state_code_val = row.get("State Code")
            if pd.notna(state_code_val) and str(state_code_val).strip():
                state_code = str(state_code_val).strip().upper()
            else:
                # BUG FIX 3: Apply misspelling corrections before STATE_CODES lookup
                state_name = row.get("State Name")
                if pd.notna(state_name) and state_name:
                    state_name_str = str(state_name).strip().title()
                    # Apply corrections
                    state_name_str = STATE_NAME_CORRECTIONS.get(state_name_str, state_name_str)
                    # Lookup in STATE_CODES
                    state_code = STATE_CODES.get(state_name_str)
                    if not state_code:
                        # Fallback: first 2 chars uppercase
                        state_code = state_name_str[:2].upper()

        # Get audit category for ATIR detection
        audit_category = row.get("Audit Category", "")
        is_atir = str(audit_category).lower() == "atir" if pd.notna(audit_category) else False

        # Get Report_No (raw, before transformation to "X of YYYY" format)
        report_no_raw = row.get("Report No", "")
        has_report_no = not (pd.isna(report_no_raw) or report_no_raw == "" or report_no_raw == "Unknown")

        year_part = None
        num_part = None

        if has_report_no:
            # Clean Report_No for filename use
            # Handle formats like "2017_10", "2017/10", "10 of 2017"
            report_no_str = str(report_no_raw).strip()

            # If it's in "X of YYYY" format, extract parts
            of_match = re.match(r"(\d+)\s+of\s+(\d{4})", report_no_str)
            if of_match:
                num_part, year_part = of_match.groups()
            # If it's in "YYYY/XX" format
            elif re.match(r"^(\d{4})[/_](\d{1,2})$", report_no_str):
                parts = re.split(r"[/_]", report_no_str)
                year_part, num_part = parts
            # If it's in "XX_YYYY" format (e.g., "06_2025")
            elif re.match(r"^(\d{1,2})_(\d{4})$", report_no_str):
                num_part, year_part = report_no_str.split("_")
            else:
                # Try to extract year from string
                year_match = re.search(r"(\d{4})", report_no_str)
                if year_match:
                    year_part = year_match.group(1)
                # Clean for use in ID
                report_no_raw = report_no_str.replace("/", "_").replace(" ", "_")

        # Fallback: Get year from Date column
        if not year_part:
            date_val = row.get("Date", "")
            if pd.notna(date_val) and date_val and date_val != "Unknown":
                date_match = re.search(r"(\d{4})", str(date_val))
                if date_match:
                    year_part = date_match.group(1)

        # Final fallback for year
        if not year_part:
            year_part = "0000"

        # P0-06: Normalize num_part to 2-digit zero-padded format
        # "4" -> "04", "10" -> "10", "" -> None
        if num_part:
            num_part = str(num_part).zfill(2)

        # Get Recommended Title (or fallback to Original Title)
        rec_title = row.get("Recommended Title", "")
        if pd.isna(rec_title) or str(rec_title).strip() == "":
            rec_title = row.get("Title", "untitled")

        # Sanitize the title
        sanitized_title = self._sanitize_filename(str(rec_title), max_length=80)

        # Build report ID based on tier
        if self.government_body_type == "union":
            # Union format: {year}_{num}_{title} or {year}_{title}
            if num_part:
                report_id = f"{year_part}_{num_part}_{sanitized_title}"
            elif has_report_no:
                report_id = f"{report_no_raw}_{sanitized_title}"
            else:
                # Fallback to SL NO
                sl_no = int(row.get('SL NO', 0))
                report_id = f"{year_part}_{sl_no:02d}_{sanitized_title}"

        elif self.government_body_type == "local_body" and is_atir:
            # Local Body ATIR format: {ST}_ATIR_{year}_{title}
            if state_code:
                report_id = f"{state_code}_ATIR_{year_part}_{sanitized_title}"
            else:
                report_id = f"ATIR_{year_part}_{sanitized_title}"

        else:
            # State/Local Body format: {ST}_{year}_{num}_{title} or {ST}_{year}_{title}
            if state_code:
                if num_part:
                    report_id = f"{state_code}_{year_part}_{num_part}_{sanitized_title}"
                else:
                    report_id = f"{state_code}_{year_part}_{sanitized_title}"
            else:
                # No state code, use simplified format
                if num_part:
                    report_id = f"{year_part}_{num_part}_{sanitized_title}"
                else:
                    sl_no = int(row.get('SL NO', 0))
                    report_id = f"{year_part}_{sl_no:02d}_{sanitized_title}"

        # P0-06: Validate report_id format at emission
        # Expected format: ([A-Z]{2}_)?{YYYY}_{NN}_... or {ST}_ATIR_{YYYY}_...
        # Where YYYY is 4-digit year, NN is 2-digit number
        self._validate_report_id_format(report_id)

        return report_id

    def _validate_report_id_format(self, report_id: str) -> None:
        """
        P0-06: Validate report_id format.

        Expected formats:
        - Union: {YYYY}_{NN}_{title} (e.g., 2025_04_Performance_Audit)
        - State: {ST}_{YYYY}_{NN}_{title} (e.g., OD_2025_01_Compliance_Audit)
        - ATIR: {ST}_ATIR_{YYYY}_{title} (e.g., KL_ATIR_2024_Annual_Report)

        Args:
            report_id: The generated report ID

        Raises:
            ValueError: If report_id format is invalid
        """
        # Define valid patterns
        patterns = [
            # Union format: YYYY_NN_title
            r"^\d{4}_\d{2}_.+$",
            # State/Local format: ST_YYYY_NN_title or ST_YYYY_title
            r"^[A-Z]{2}_\d{4}_(?:\d{2}_)?.+$",
            # ATIR format: ST_ATIR_YYYY_title
            r"^[A-Z]{2}_ATIR_\d{4}_.+$",
            # Legacy format with Report No: e.g., 10_of_2017_title (for backward compat)
            r"^\d+_of_\d{4}_.+$",
        ]

        is_valid = any(re.match(p, report_id) for p in patterns)

        if not is_valid:
            logger.warning(
                f"P0-06: Report ID format validation warning: '{report_id}' "
                f"does not match expected patterns. This may cause issues with "
                f"downstream processing."
            )
            # Don't raise - just warn for now to avoid breaking existing workflows
            # In production, this could be upgraded to an assertion

    def _check_legacy_report_id(self, canonical_report_id: str) -> Optional[Path]:
        """
        P0-06: Check if a legacy format file exists for this report.

        Legacy format uses non-zero-padded numbers (e.g., 2025_4 instead of 2025_04).

        Args:
            canonical_report_id: The canonical (zero-padded) report ID

        Returns:
            Path to legacy file if it exists, None otherwise
        """
        # Try to convert canonical format to legacy format
        # Canonical: 2025_04_title or OD_2025_04_title
        # Legacy: 2025_4_title or OD_2025_4_title

        # Pattern: find _NN_ where NN starts with 0 and replace with _N_
        legacy_id = re.sub(
            r"_0(\d)_",  # Match _0X_ pattern
            r"_\1_",      # Replace with _X_
            canonical_report_id,
            count=1       # Only replace first occurrence
        )

        if legacy_id != canonical_report_id:
            legacy_path = self.raw_data_dir / f"{legacy_id}.pdf"
            if legacy_path.exists():
                return legacy_path

        return None

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def _download_pdf(
        self, client: httpx.AsyncClient, row: pd.Series
    ) -> DocumentTask:
        """
        Download a single PDF report with complete metadata.

        PHASE 3 FIX: Now passes all metadata fields to DocumentTask.
        FILE NAMING UPDATE: Uses Report_No_Recommended_Title format.

        Args:
            client: Async HTTP client
            row: Row from manifest DataFrame

        Returns:
            DocumentTask instance
        """
        url = row["Report PDF"]
        title = row["Title"]

        # Build report ID using new naming convention
        rec_title = row.get("Recommended Title", "")
        if pd.isna(rec_title) or str(rec_title).strip() == "":
            rec_title = row.get("Title", "untitled")
        report_id = self._build_report_id(row)
        local_path = self.raw_data_dir / f"{report_id}.pdf"

        # Trace: Report ID generation
        self._trace_emitter.emit(
            "1",
            "report_id_generation",
            {
                "raw_title": str(rec_title)[:50],
                "report_id": report_id,
                "tier": self.government_body_type,
            },
        )

        # Check if PDF already exists (primary or fallback filenames)
        existing_pdf_path = None
        match_strategy = None

        if local_path.exists():
            existing_pdf_path = local_path
            match_strategy = "exact"
        else:
            # P0-06: Fallback check for legacy format (without zero-padding)
            # e.g., 2025_4_title.pdf instead of 2025_04_title.pdf
            legacy_path = self._check_legacy_report_id(report_id)
            if legacy_path and legacy_path.exists():
                existing_pdf_path = legacy_path
                match_strategy = "legacy_format_fallback"
                logger.info(f"  P0-06: Found PDF with legacy format: {legacy_path.name[:60]}...")

            # Fallback: Check for Original Title filename (for manually downloaded PDFs)
            if not existing_pdf_path:
                original_title = row.get("Title", "")  # "Title" is mapped from "Original Title"
                if not pd.isna(original_title) and original_title:
                    original_title_path = self.raw_data_dir / f"{original_title}.pdf"
                    if original_title_path.exists():
                        existing_pdf_path = original_title_path
                        match_strategy = "original_title_fallback"
                        logger.info(f"  Found PDF with Original Title: {original_title_path.name[:60]}...")

        if existing_pdf_path:
            # File already exists, skip download and return task
            metadata = self._build_metadata(row, title)

            # Trace: PDF resolution decision
            self._trace_emitter.emit_decision(
                "1",
                "pdf_resolution",
                match_strategy,
                ["exact", "legacy_format_fallback", "original_title_fallback", "download"],
                f"Found existing PDF at {str(existing_pdf_path)[-50:]}",
            )

            return DocumentTask(
                report_id=report_id,
                source_url=url,
                local_pdf_path=str(existing_pdf_path),
                initial_metadata=metadata,
            )

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        # Build complete metadata dict
        metadata = self._build_metadata(row, title)

        # Log metadata for debugging
        if self.government_body_type == "union":
            logger.debug(
                f"  Metadata for {report_id}: "
                f"Report No='{metadata['Report No']}', "
                f"Ministry='{metadata.get('Ministry', 'N/A')}', "
                f"Type='{metadata['Report Type']}'"
            )
        else:
            logger.debug(
                f"  Metadata for {report_id}: "
                f"State='{metadata.get('state_name', 'N/A')}', "
                f"Dept='{metadata.get('department', 'N/A')}', "
                f"Category='{metadata.get('audit_category', 'N/A')}'"
            )

        try:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

            # Trace: PDF resolution - downloaded
            self._trace_emitter.emit_decision(
                "1",
                "pdf_resolution",
                "download",
                ["exact", "original_title_fallback", "download"],
                f"Downloaded from {url[:50]}",
            )

            return DocumentTask(
                report_id=report_id,
                source_url=url,
                local_pdf_path=str(local_path),
                initial_metadata=metadata,  # Now includes all fields
            )
        except Exception as e:
            # Trace: PDF resolution - failed
            self._trace_emitter.emit_decision(
                "1",
                "pdf_resolution",
                "download_failed",
                ["exact", "original_title_fallback", "download", "download_failed"],
                f"Download failed: {str(e)[:100]}",
            )

            failed_task = DocumentTask(
                report_id=report_id,
                source_url=url,
                local_pdf_path="",
                initial_metadata=metadata,
                processing_status="failed_download",
                error_log=[f"Download failed after retries: {str(e)}"],
            )
            return failed_task

    async def process_manifest(self, manifest_path: str) -> List[DocumentTask]:
        """
        Main method to process the manifest and download PDFs.

        Args:
            manifest_path: Path to the Excel manifest

        Returns:
            List of DocumentTask objects
        """
        df = self.load_manifest(manifest_path)
        tasks = []

        # Limit concurrent connections to avoid overwhelming the server
        limits = httpx.Limits(max_connections=5, max_keepalive_connections=5)
        async with httpx.AsyncClient(limits=limits, timeout=30.0) as client:
            for _, row in df.iterrows():
                task = await self._download_pdf(client, row)
                tasks.append(task)

        # Log summary
        successful = [t for t in tasks if t.processing_status != "failed_download"]
        failed = [t for t in tasks if t.processing_status == "failed_download"]
        logger.info(
            f"Ingestion complete: {len(successful)} downloads successful, {len(failed)} failed."
        )
        logger.info(f"Government body type: {self.government_body_type}")
        logger.info(f"PDF storage directory: {self.raw_data_dir}")

        # Log metadata coverage (tier-specific)
        if self.government_body_type == "union":
            metadata_complete = sum(
                1
                for t in successful
                if t.initial_metadata.get("Report No") != "Unknown"
                and t.initial_metadata.get("Ministry") != "Unknown"
            )
            logger.info(
                f"Metadata coverage: {metadata_complete}/{len(successful)} reports have complete metadata"
            )
        else:
            # State/Local: check for state_name
            metadata_complete = sum(
                1
                for t in successful
                if t.initial_metadata.get("state_name") is not None
            )
            logger.info(
                f"Metadata coverage: {metadata_complete}/{len(successful)} reports have state_name"
            )

        return tasks
