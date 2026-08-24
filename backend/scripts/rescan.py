import scripts._bootstrap  # noqa: F401
import sys

sys.stdout.reconfigure(encoding="utf-8")
from food_inspection.store import scan_data

result = scan_data()
stats = result["stats"]
print("合格:", stats["qualified_count"])
print("不合格:", stats["unqualified_count"])
print("有效文件:", stats["parsed_files"], "/", stats["total_files"])
print("\n各省统计:")
for prov, info in sorted(stats["provinces"].items()):
    print(
        f"  {prov}: 文件{info['files']}个 | "
        f"合格{info['qualified']}条 | 不合格{info['unqualified']}条"
    )
