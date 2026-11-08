# 0.1.3 验证记录与维护状态

日期：2026-11-08  
版本：`0.1.3`  
Commit：`ceb8473`  
Tag：`v0.1.3`

## 结论

0.1.3 的安装/清理自动化验收通过，发布资产审计通过；原始 `call_id`
问题仍无法复现，因此只记录为“不可复现 + 实验性 workaround”，不标记为
“已修复”。

项目从本记录起进入**维护/验证阶段**：

- 功能冻结；
- 只处理可复现 bug、安全修复、兼容性回归；
- 不把“无法复现”写成“已修复”。

## 验证范围与环境

### 本地环境

```text
Windows 10 19045
Python 3.10 / Node（构建环境）
当前用户，非管理员安装
```

本地验证过：

- `node --test`：通过；
- `python -m py_compile gui/app.py packaging/installer.py`：通过；
- portable 解压运行：EXE 旁不产生 `_MEI*`；
- setup 窗口化 `--silent` 安装：`result.json` 为 `ok: true`；
- cleanup：项目子证书删除，根在无其他子证书时删除；`-RemoveFolder` 可删除目录；
- 0.1.3 release：CI 构建成功。

### 干净 runner

```text
GitHub Actions / windows-latest
工作流：verify
运行：42448536847
https://github.com/Hungry-M/codex-callid-fix/actions/runs/42448536847
```

该 job 的 `Install, verify, and cleanup on a clean runner` 步骤成功。
验证内容：

- `--silent` 安装到 runner 临时目录；
- `result.json` 为 `ok: true`；
- 安装目录包含 `CodexCallIdFix.exe`、`cleanup.ps1`；
- 安装目录没有 `_MEI*`；
- `cleanup.ps1 -Yes -KeepBackups -RemoveFolder` 删除安装目录；
- portable ZIP 包含 `cleanup.ps1`，portable cleanup 可执行。

### 范围限制

这个 runner **不是**最终用户的 Windows 11/Explorer 环境，且为构建安装了
Python/Node。因此本记录**不覆盖**：

- 交互式 SmartScreen / Defender 在另一台设备上的表现；
- Windows 11 实机；
- 全新 Windows 用户、无 Python/Node 的 PATH 隔离；
- 从 0.1.2 升级到 0.1.3 的实机升级；
- Windows“应用和功能”里的交互式卸载；
- 不同杀毒软件/企业策略。

这些未覆盖项不能被标记为通过。

## 三项验收

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 1. 干净环境安装/清理 | **PASS（CI 范围）** | `verify` 运行 42448536847，安装/清理步骤成功 |
| 2. 原问题状态 | **RECORDED：不可复现** | 开发机 + 第二台测试机均未复现；无完整请求样本 |
| 3. 发布审计 | **PASS** | v0.1.3 构建成功；13 个手工资产，无裸 EXE；SHA256SUMS 可复核 |

第 1 项只代表“自动化安装/清理验收通过”，不代表完整用户 UX 矩阵通过。

## 原始问题状态

`call_id` 合成 `function_call_output` 的 workaround 仍是实验性的：

- 开发机和第二台机器都未复现原始失败；
- 没有捕获到可分析的完整请求；
- 现有 rewrite 逻辑有单元测试，但不能证明真实 Codex 场景已修复；
- 对外描述应使用“workaround / 无法复现”，不要使用“fixed”。

后续如果出现报告，需要：

1. Codex 版本、Windows 版本、安装方式（setup/portable）；
2. 是否启用 proxy/egress 模式；
3. 脱敏后的请求形态（只保留 call_id/工具调用结构，不含 token/API key）；
4. `backend/server.log` 相关片段；
5. 是否能稳定复现。

不要收集 `.codex` 的 auth/state 或 API key。

## 发布审计

Release：

```text
https://github.com/Hungry-M/codex-callid-fix/releases/tag/v0.1.3
```

资产：

- setup 1 个；
- portable 1 个；
- `SHA256SUMS.txt`；
- README / README.zh / README.zh-Hant；
- LICENSE / AUTHORS / CHANGELOG / SECURITY / CONTRIBUTING /
  CODE_OF_CONDUCT / THIRD_PARTY_NOTICES；
- GitHub 自动生成的 source zip/tar 2 个。

不再发布裸 `CodexCallIdFix.exe`。

## 维护规则

进入维护/验证后：

- 不主动加新功能；
- 0.1.3 为当前稳定版本；
- 只有以下情况发 0.1.4：
  - 可复现的 `call_id` 回归；
  - 安全/隐私问题；
  - 安装、卸载、cleanup 的明确回归；
  - Codex 新版本导致的兼容性破坏；
- 每次发版前运行 `verify` 工作流和 `packaging/build.ps1`；
- 自签名仍只作为本机可选工具，不作为公共信任方案；
- CA 签名、onedir/Inno Setup、独立 cleanup 工具明确 park，不阻塞维护。

## 复核触发条件

满足任一条件时重新打开验证：

- 收到可复现的 `call_id` 报告；
- Codex Desktop 大版本更新；
- Windows 11/企业策略出现安装/卸载差异；
- cleanup 或证书清理出现误删/残留报告；
- 决定公开分发并要求消除 Defender/SmartScreen 误报。

## 相关文档

- [`docs/reproduce.md`](reproduce.md)
- [`docs/environment.md`](environment.md)
- 工程笔记：`D:\Documents\dev-notes\docs\windows\install-uninstall.md`
- 工程笔记：`D:\Documents\dev-notes\docs\windows\local-self-signing.md`
