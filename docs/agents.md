# AI 技能安装

CiteCargo 技能让 AI 代为安装工具、执行下载、核验结果并交付文件。需要能在本机执行命令的助手，以及 Python 3.10+；纯聊天客户端只导入说明文字无法运行。

## V2 离线包

本分支技能包包含 `vendor/wheels/`、启动脚本与 `bundle-manifest.json`。wheel 是唯一内置引擎，避免源码与安装包双份维护。包初始化时不修改自身，在用户缓存目录建立独立运行环境，使用 `--no-index`、锁定哈希和 `--no-deps`，再校验依赖与 CLI 版本。

```bash
python "<技能目录>/scripts/bootstrap.py" --diagnose
python "<技能目录>/scripts/citecargo.py" --version
```

需要完整 Python 3.10+，包括 venv 和 ensurepip；缺少时请用户补齐，不自动联网安装。`CITECARGO_RUNTIME_CACHE` 可指定用户可写的缓存根目录，但不能放在技能包内部。

源码里的指令文件夹尚无 `bundle-manifest.json` 与 wheel，不能当作完整离线安装包。正式跨平台包需 Windows、Linux、macOS × Python 3.10、3.13 的同一载荷验证齐全；候选包清单会标记实际验收范围。

## Codex

从[发布页](https://github.com/Xplore-LAB/paper-tool/releases/latest)下载技能压缩包，解压后将整个 `citecargo` 文件夹放进 `~/.codex/skills/`。Windows 对应当前用户目录中的 `.codex/skills/`。重开会话后使用：

> 用 $citecargo 下载这些论文，只要正文，保存在我的课题目录。

> 用 $citecargo 把这些论文补入 Zotero 的“已有分类完整路径”，并获取可用全文。

其他支持 `SKILL.md` 的助手，按其文档安装同一技能文件夹；是否能自动发现、是否能运行本机命令取决于客户端。

## 维护入口

唯一技能源文件是 [skills/citecargo/SKILL.md](../skills/citecargo/SKILL.md)，界面信息位于同目录 `agents/openai.yaml`。不再复制维护第二套操作规则。

AI 应复用已有环境和下载目录，默认只下载正文、不连接 Zotero。归档沿用用户已授权的已有分类，缺少明确目标时再询问。实际命令与状态见[使用手册](usage.md)。
