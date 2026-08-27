# 贡献指南（CONTRIBUTING）

感谢你愿意参与 **MCWConverter** 的开发。本指南覆盖：开发环境搭建、代码规范、分支与提交规范、版本号策略，以及**首次开源发布**的完整 Git 操作步骤。

---

## 1. 开发环境搭建

需要 **Python 3.12** + CMake（部分依赖编译）与 Windows 10/11（WebView2 运行时）。

```powershell
# 1) 创建虚拟环境
py -3.12 -m venv .venv
.\.venv\Scripts\activate

# 2) 安装依赖（见 requirements.txt 顶部注释）
#    amulet-core 的硬依赖 amulet-rocksdb 是 C++ 扩展，需 --no-deps 安装，
#    由 backend/rocksdb_stub 纯 Python 占位包替代。
pip install --no-deps amulet-core==1.9.44
pip install -r requirements.txt

# 3) 源码直接运行（开发调试）
python run.py

# 4) 打包单 exe（输出到仓库根目录 ../release）
pyinstaller --noconfirm --distpath ..\release --workpath build\work build\MCWConverter.spec
```

> `amulet-core` / `PyMCTranslate` 体积较大且内部用动态导入，spec 里用 `os.walk`
> 手工收集子模块与数据文件，**不要**改回 `collect_submodules`（隔离子进程会因
> rocksdb 未注册而失败）。

## 2. 代码规范

- 语言：注释与 UI 文案一律**中文**；代码标识符用英文。
- Python：遵循 PEP 8；后端按模块职责划分（`decrypt`/`convert`/`detect`/`leveldat`/`api`），
  新增逻辑优先复用现有模块。
- 前端：`web/app.js` 为原生 JS（无构建步骤），修改后必须通过
  `node --check web/app.js` 语法校验。
- 隐私红线（**必须**）：
  - 禁止在代码/文档中出现**真实存档名、玩家名、本机绝对路径**（例如 `<本机路径>\...`、
    `<虚拟环境路径>\...`）。
  - 运行产物 `work/`、`build/work/`、`release/` 已在 `.gitignore`，不要手动提交。
  - 提交前自检：`grep -riE "<你的存档名>|<你的用户名>|<本机路径特征>|C:\\Users|D:\\Apps" --include="*.py" --include="*.js" --include="*.md" .`（应无命中）。

## 3. 分支管理策略

| 分支 | 用途 | 说明 |
| --- | --- | --- |
| `main` | 稳定发布分支 | 只接受 `release/*` 合并与 hotfix，永远可构建可运行 |
| `develop` | 集成分支 | 功能分支完成后合入；发布时从 `develop` 切 `release/*` |
| `feature/*` | 功能开发 | 从 `develop` 切出，命名如 `feature/zip-import` |
| `release/*` | 发布准备 | 只做修 bug、文档、版本号，不改功能 |
| `hotfix/*` | 线上紧急修复 | 从 `main` 切出，修复后同时合回 `main` 与 `develop` |

单人小型项目可简化：直接在 `main` 上开发，但**建议**至少开 `feature/*` 分支做实验性改动。

## 4. 提交规范

采用 [Conventional Commits](https://www.conventionalcommits.org/) 风格：

```
<type>(<scope>): <描述>

feat(api): 支持 zip 压缩包导入
fix(exit): 修复关闭时 _MEI 临时目录清理失败
docs(readme): 补充安装说明
refactor(detect): 提取维度信息解析
```

- `type`：`feat` / `fix` / `docs` / `refactor` / `perf` / `test` / `chore` / `revert`
- 描述用**中文**，动词开头、简洁完整。
- 一个提交只做一件事；不要把格式化与功能改动混在一起。
- 提交前运行：`node --check web/app.js`、`python -m py_compile backend/*.py run.py`。

## 5. 版本号设定（SemVer）

格式 `主.次.补丁`（如 `1.0.0`）：

- **主版本**：不兼容的架构/行为变更（如解密算法更换）。
- **次版本**：向后兼容的新功能（如新增导入格式）。
- **补丁版本**：向后兼容的 bug 修复。

发布版本时同步更新：`README.md` 的"功能"章节（如有新增）、Git tag（`v` 前缀）。

## 6. 首次开源发布：完整 Git 操作指南

以下步骤从「尚未初始化仓库」开始，完整覆盖初始化 → 提交 → 打标签 → 推送 → 发布说明。

### 6.1 前置检查

```powershell
# 在仓库根目录执行
cd <你的项目根目录>

# 1) 确认 .gitignore 生效、没有敏感文件会被提交
git status --porcelain --ignored   # 应看到 work/ build/work/ release/ 被忽略

# 2) 确认没有敏感内容残留
git grep -iE "<你的存档名>|<你的用户名>|<本机路径特征>|C:\\Users|D:\\Apps"   # 应无输出
```

### 6.2 初始化仓库与首次提交

```powershell
# 初始化（main 为默认分支名）
git init -b main

# 全局身份（如未配置过）
git config --global user.name "你的名字"
git config --global user.email "you@example.com"

# 暂存全部应提交文件并查看将提交的清单
git add .
git status

# 提交首个版本
git commit -m "feat: 初始发布 - 网易加密存档转 Java 版桌面转换器"
```

> 若 `git status` 出现 `.env`、`*.key`、`*.pem`、`config.json` 等，先加入
> `.gitignore` 再提交，**切勿**提交密钥类文件。

### 6.3 分支与保护

```powershell
# 若计划多分支协作：创建并切换到 develop
git switch -c develop

# 本地开发完成后合回 main（发布走 release/* 分支亦可）
git switch main
git merge --no-ff develop -m "merge: develop 合入 main 准备发布"
```

（GitHub 端可再配置分支保护规则：`main` 禁止直接 push、要求 PR 与 CI 通过。）

### 6.4 发布前收尾

```powershell
# 确认版本号与 README 描述一致；更新 README "功能/已知限制" 若有必要
git add .
git commit -m "chore: 发布前文档与版本号整理"
```

### 6.5 创建发布标签

```powershell
# 语义化版本标签（带 v 前缀，附注说明）
git tag -a v1.0.0 -m "MCWConverter v1.0.0 - 首次发布"

# 查看标签
git tag -l

# 如需补丁：在修复并提交后
#   git tag -a v1.0.1 -m "MCWConverter v1.0.1 - 修复..."; git push origin v1.0.1
```

### 6.6 关联远程仓库并推送

```powershell
# 在 GitHub/Gitee 新建空仓库后（不要勾选"初始化 README/LICENSE"以避免冲突）
git remote add origin https://github.com/<用户名>/MCWConverter.git

# 推送主分支并设置上游跟踪
git push -u origin main
# 若使用 develop：
git push -u origin develop

# 推送标签
git push origin v1.0.0
# 或推送全部标签： git push --tags
```

### 6.7 编写发布说明（GitHub Releases）

发布说明建议包含：

1. **标题**：`MCWConverter v1.0.0` + 一句话简介。
2. **下载**：单文件 exe 的校验信息，例如
   `SHA256: <hash>`（在 PowerShell 中运行
   `Get-FileHash .\release\MCWConverter.exe -Algorithm SHA256` 获取）。
3. **新功能 / 变更 / 修复**：按 Conventional Commits 的 type 归类列出。
4. **兼容性**：支持的操作系统、Java 版本、已知限制。
5. **致谢**：依赖与上游项目（amulet-core、NetEaseMC-Decryptor 等）。

> 在 GitHub 网页端 "Releases → Create a new release" 选择 `v1.0.0` 标签，
> 粘贴以上内容发布即可；**禁止**把 exe 打进源码仓库，应作为 Release 附件上传。

### 6.8 发布后检查清单

- [ ] `git ls-remote --tags origin` 能看到 `v1.0.0`
- [ ] Release 附件（exe）已上传且附 SHA256
- [ ] 远程仓库无 `work/`、`build/work/`、`release/`、`*.exe`、密钥文件
- [ ] 从全新 clone 可完成 `pip install -r requirements.txt` 并按 README 构建

---

## 7. 问题反馈

发现 bug 或功能建议，请到仓库 Issues 提交，尽量包含：操作系统版本、Java 版本、
复现步骤、报错截图。涉及存档转换问题时**不要**上传真实存档文件（含个人数据），
可用仅含结构的测试存档复现。
