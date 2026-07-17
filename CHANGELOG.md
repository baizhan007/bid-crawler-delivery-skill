# Changelog

本项目遵循面向功能的变更记录；日期使用 `YYYY-MM-DD`。

## [1.0.0] - 2026-07-17

### Added

- 新增 `bidfactory` CLI，提供 `new`、`capture`、`replay`、`validate`、`diff`、`package` 和 `doctor` 七个命令。
- 新增版本化 HTML/JSON fixture、站点 adapter、严格离线回放和本地模拟招投标站点。
- 新增必填字段、重复、日期范围、href、栏目覆盖和正文质量验收报告。
- 新增 JSON 路径/类型与关键 DOM 选择器变化检测。
- 新增一站一项目交付目录、ZIP、SHA-256 清单及独立复核。
- 新增 pytest 回归测试和自包含 Skill eval 场景。

### Changed

- 交付 CSV 明确为最多 20 条的验收样本，正式流程以源码直接写入 `a_bidcollect_info` 为准。
- 验收器重新计算关键指标，不再信任既有报告中的通过布尔值。
- Skill 文档、字段映射、输出目录和 CLI 工作流保持一致。

### Fixed

- 修复模板验收报告中未定义的 `href_bad`。
- 修复一个栏目遇到连续旧记录后错误终止后续栏目采集的问题。
- 源码语法检查改用内存 `compile()`，避免生成 `__pycache__`。
- 统一字段映射、状态文件、验收样本和验收报告的交付路径。

### Security

- 录制时限制允许主机、响应类型、响应大小和重定向，并脱敏 Cookie、Authorization、Token、密码及敏感查询参数。
- 回放时阻断网络访问，fixture 拒绝路径逃逸。
- 打包前扫描硬编码秘密、缓存、VCS 和调试残留；数据库表名采用严格标识符校验。
