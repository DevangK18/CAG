from src.rag_pipeline.auto_filter import AutoFilterExtractor
from src.core.config import AutoFilterConfig
ext = AutoFilterExtractor(AutoFilterConfig())
print(ext.extract("Kerala 2020-21 findings"))
print(ext.extract("Kerala local body audit findings"))
print(ext.extract("Kerala panchayat irregularities"))