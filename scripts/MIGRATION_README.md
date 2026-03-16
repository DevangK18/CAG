# Union Data Migration - Add Multi-Tier Fields

This script adds multi-tier fields to existing Union data that has already been moved to `data/processed/union/`.

## Prerequisites

Files must already be in the tier directories:
- `data/processed/union/` - JSON files (*_chunks.json, *_overview.json, manifest.json)
- `data/raw/union/` - PDF files

## What This Script Does

The script updates JSON files **IN PLACE** by adding these tier-specific fields:
- `government_body_type: "union"`
- `state_name: null`
- `department: null`
- `audit_category: <inferred from report_type>`
- `report_subtype: null`

### Files Updated

**For `*_chunks.json` files:**
- Adds tier fields to `report_metadata`
- Adds tier fields to each entry in `child_chunks` array
- Adds tier fields to each entry in `parent_chunks` array

**For `*_overview.json` files:**
- Adds tier fields to `basic_info` object

**For `manifest.json`:**
- Adds tier fields to each report entry

## Usage

### 1. Preview Changes (Dry Run)

```bash
python scripts/migrate_union_data.py
```

Shows what would be updated without making changes.

Example output:
```
Found 39 JSON files in data/processed/union

  [DRY RUN] Would update: 2023_11_CAGs_Performance_Audit_chunks.json
            Audit category: performance
            Child chunks: 1126
  ...

JSON Update Summary:
  Chunks files:     19
  Overview files:   19
  Total child chunks updated: 15669
```

### 2. Execute Updates

```bash
python scripts/migrate_union_data.py --execute
```

Updates all files IN PLACE with tier fields.

**Important:** This modifies existing files. Make sure you have backups!

### 3. Verify Updates

After executing, the script automatically verifies the updates:

```
VERIFICATION
================================================================================
Files in data/processed/union:
  *_chunks.json files:   19
  *_overview.json files: 19

✓ Tier fields found in 2020_16_Performance_Audit_chunks.json:
    government_body_type: union
    audit_category:       performance
✓ Tier fields found in child chunks

✓ Verification PASSED
```

## Audit Category Inference

The script infers `audit_category` from the existing `report_type` field:

| Report Type | Audit Category |
|-------------|----------------|
| Performance Audit | `performance` |
| Compliance Audit | `compliance` |
| Financial Audit | `financial` |
| FRBM Compliance Audit | `financial` |
| Revenue Audit | `revenue` |
| Commercial Audit | `commercial` |
| Unknown/Other | `compliance` (default) |

## Example: Before and After

### Before (`report_metadata`):
```json
{
  "report_id": "2023_11",
  "report_number": "11 of 2023",
  "report_type": "Performance Audit",
  "title": "Ayushman Bharat...",
  "ministry": "Ministry of Health",
  "sector": "Social Sector"
}
```

### After (`report_metadata`):
```json
{
  "report_id": "2023_11",
  "report_number": "11 of 2023",
  "report_type": "Performance Audit",
  "title": "Ayushman Bharat...",
  "ministry": "Ministry of Health",
  "sector": "Social Sector",
  "government_body_type": "union",
  "state_name": null,
  "department": null,
  "audit_category": "performance",
  "report_subtype": null
}
```

The same fields are added to every entry in `child_chunks` and `parent_chunks` arrays.

## Safety Features

1. **Dry Run Default**: Preview changes before executing
2. **In-Place Updates**: Files are modified directly (no copying)
3. **Automatic Verification**: Checks that tier fields were added correctly
4. **Error Handling**: Reports any files that fail to update

## Troubleshooting

### No JSON files found

Error: `ERROR: data/processed/union directory not found!`

**Solution:** Ensure files have been moved to `data/processed/union/` first.

### Updates Failed

If verification fails:
1. Check error messages in the output
2. Manually inspect a sample file to see what went wrong
3. Restore from backup if needed

### Missing Fields After Update

If verification shows missing fields:
- Check that the original JSON has the expected structure
- `*_chunks.json` should have `report_metadata`, `child_chunks`, `parent_chunks`
- `*_overview.json` should have `basic_info`

## Next Steps After Migration

1. **Test Pipeline**: Run the parsing pipeline to verify it reads tier fields correctly
2. **Test API**: Ensure the API serves data with tier fields
3. **Test Frontend**: Verify frontend handles the new fields
4. **Index to Qdrant**: Re-index data if needed (chunks now have tier fields)

## Rolling Back

If you need to roll back:
1. Restore from backup (files were modified in place)
2. Or remove the tier fields manually:
   ```python
   # Remove these keys from report_metadata and chunks
   del data['report_metadata']['government_body_type']
   del data['report_metadata']['state_name']
   del data['report_metadata']['department']
   del data['report_metadata']['audit_category']
   del data['report_metadata']['report_subtype']
   ```

**Always keep backups before running the migration!**
