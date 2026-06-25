# Contributing

欢迎改进这个 Skill。改动时请优先保持以下设计原则：

- 面向甲方交付，而不是只面向开发调试。
- 每个网站独立项目。
- 默认单文件 Python 爬虫。
- 中文注释和中文交付文档。
- 默认以 `a_bidcollect_info` 直接入库作为正式交付物，CSV 只作为样本验收材料。
- 支持增量和断点采集。
- 最终目录必须干净。

## 修改后检查

```powershell
python -m py_compile templates/single_site_crawler_template.py scripts/scaffold_site_project.py scripts/validate_delivery.py
```

如有示例交付目录，可运行：

```powershell
python scripts/validate_delivery.py "交付根目录"
```
