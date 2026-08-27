# MCWConverter · 网易存档转换器

一个**本地桌面应用**，把网易（中国版）《我的世界》基岩版存档转换为标准 **Java 版** 存档。

网易基岩版存档使用专有 LevelDB 加密（文件头 `80 1D 30 01` + 正文 XOR），标准工具（含 Amulet）无法直接读取。本工具在**本地**完成「解密 → 转换为 Java Anvil → 重建 level.dat」全流程，**不上传任何数据**。

## 功能

- **多种导入方式**：选择网易加密存档文件夹，或导入压缩包（`.zip` / `.mcworld` / `.mctemplate` / `.tar`，自动解压并定位世界根目录）
- **本地解密**：网易专有加密全程在副本上操作，**不修改原存档**
- **转为 Java 版**（Anvil 格式），默认目标 **Java 1.20.4**；可指定其他稳定版本，降级时给出有损提示
- **实时进度**：解密文件数 / 转换区块数
- **完整 `level.dat`**：含世界生成设置、种子、出生点、游戏规则，可直接被 Java 版 / PCL2 读取
- **自定义存档名**：默认按「原存档名_Java_版本号」命名（如 `我的世界_Java_1.20.4`），可手动修改；重名自动追加序号避免覆盖
- **可靠保存**：保存前写权限预检，被安全软件拦截时给出中文指引；支持保存到应用工作目录作为兜底
- **全中文界面**，四步向导清晰明了

## UI

基于 Minecraft 像素风（直角、像素字体、灰白底 + 高饱和语义色）的四步向导：

`选择世界 → 导出为 → 转换中 → 保存世界`

## 安装

### 方式一：直接运行（推荐）

1. 下载最新版 `MCWConverter.exe`（见 GitHub Releases）。
2. 双击运行。需要系统已安装 [WebView2 运行时](https://developer.microsoft.com/microsoft-edge/webview2/)（Windows 10/11 通常已自带）。

### 方式二：从源码构建

需要 **Python 3.12** + CMake（部分依赖编译）。

```powershell
# 1) 创建虚拟环境并安装依赖
py -3.12 -m venv .venv
.\.venv\Scripts\activate

# 2) amulet-core 的硬依赖 amulet-rocksdb 是 C++ 扩展（需 MSVC 编译，纯 pip 会失败），
#    以 --no-deps 安装，并由 backend/rocksdb_stub 纯 Python 占位包替代
pip install --no-deps amulet-core==1.9.44
pip install -r requirements.txt

# 3) 源码直接运行（开发调试）
python run.py

# 4) 打包单 exe
pyinstaller --noconfirm --distpath ..\release --workpath build\work build\MCWConverter.spec
```

## 使用

1. 启动应用，点击 **选择世界文件夹**（或 **选择存档压缩包**）。
2. 应用自动探测存档：世界名 / 平台 / 版本 / 各维度区块数。
3. 在 **导出为** 步骤选择目标 Java 版本（默认推荐 1.20.4）。
4. 点击 **转换**，等待进度完成。
5. 在 **保存世界** 步骤确认存档名称（默认「原存档名_Java_版本号」），选择 **保存** 指定输出目录；若目标目录被安全软件拦截，可改用 **保存到应用目录**。
6. 把导出文件夹复制到 Java 版的 `saves/` 目录即可游玩（PCL2 等启动器可直接读取）。

## 技术原理

- **解密**：密钥由 `db/CURRENT` 与 `db/MANIFEST-*` 文件名推导
  `key = xor(CURRENT[4:], manifest_name + "\n")`，对带加密头的文件做 XOR 还原。
- **转换**：`amulet-core` 读取解密后的 LevelDB，转写为 Java Anvil。
- **level.dat 重建**：补齐 `WorldGenSettings`/种子/出生点/游戏规则等字段，确保 Java 判定有效。
- **运行环境**：打包模式下工作目录（临时文件、WebView2 用户数据、amulet 缓存）置于 exe 同级 `work/`，避免落入 PyInstaller `_MEI` 临时目录导致退出清理失败。

## 已知限制

- 网易「资源工坊」存档有二次加密，本工具无法处理。
- 跨平台转换固有：实体（怪物/动物）不保留、物品可能丢失、平台特有方块替换为最接近的原版方块。
- 版本降级有损。
- 未来版本（如 26.x）因新式维度布局暂不支持作为转换目标（默认推荐 1.20.4）。

## 贡献

欢迎提交 Issue 与 Pull Request。请遵循以下约定：

- 注释与 UI 文案使用中文，遵循仓库既有代码风格；
- 不提交含真实存档名、玩家名或本机绝对路径的内容；
- 修改 `web/app.js` 后请通过 `node --check web/app.js` 校验语法；
- 提交信息采用 Conventional Commits 风格（`feat:` / `fix:` / `docs:` 等）。

## 免责声明

本工具仅供将**自身合法拥有**的存档进行个人数据迁移。请遵守相关法律法规与《我的世界》服务条款，**禁止**用于处理他人存档或任何侵权用途。按「原样」提供，不附带任何明示或默示担保，使用风险自担。

## 第三方组件

- [amulet-core](https://github.com/Amulet-Team/Amulet-Map-Editor) / PyMCTranslate / amulet-nbt（Amulet Team）
- [NetEaseMC-Decryptor](https://github.com/ihaiming/NetEaseMC-Decryptor) — 网易 XOR 解密算法来源（GPL-3.0）
- [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P) 像素字体（OFL）
- [pywebview](https://pywebview.flowrl.com/)（BSD）
- numpy / lz4 / portalocker / platformdirs 等（各自许可）

## License

[GPL-3.0](LICENSE)（与解密算法上游保持一致）
