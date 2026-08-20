# Magic Toys 🚀

> **Magic Toys** 是一个基于 **Python** 开发、专为容器、边缘平台（PaaS/Serverless）以及 VPS 设计的轻量级高性能代理协议服务端脚本。
>
> 项目原生支持 **VLESS** / **Trojan** + **WS** / **gRPC** / **xhttp** 传输协议，以及 **Shadowsocks (SS)** + **WS** 传输协议，导出标准 **v2ray Base64** 订阅格式。
>
> 💡 **推荐客户端**：强烈建议使用 **[Karing](https://github.com/KaringX/karing)** 客户端，享受最完整、稳定的多协议及传输层支持。

---

## 📑 目录

- [🚀 快速开始与多平台部署](#-快速开始与多平台部署)
  - [1. ⚡ VPS 极速一键安装与管理向导 (置顶推荐)](#1--vps-极速一键安装与管理向导-置顶推荐)
  - [2. 📂 仅允许上传文件部署的平台 (无 Docker / 纯代码环境)](#2--仅允许上传文件部署的平台-无-docker--纯代码环境)
  - [3. 🐳 Docker 与 PaaS 容器平台部署 (Fork 自动构建)](#3--docker-与-paas-容器平台部署-fork-自动构建)
- [🔗 核心访问路径：订阅链接与设置后台](#-核心访问路径订阅链接与设置后台)
- [🌟 功能特性](#-功能特性)
- [⚙️ 环境变量配置指南 (重点)](#-环境变量配置指南-重点)
  - [1. 核心网络与身份标识](#1-核心网络与身份标识)
  - [2. 协议与传输层开关](#2-协议与传输层开关)
  - [3. 数据库与持久化配置](#3-数据库与持久化配置)
  - [4. 哪吒监控面板集成 (Nezha)](#4-哪吒监控面板集成-nezha-monitoring-agent)
- [☁️ Cloudflare CDN 与 NAT VPS 回源配置](#️-cloudflare-cdn-与-nat-vps-回源配置-nat-vps-必看)
- [📱 客户端订阅导入 (Karing)](#-客户端订阅导入-karing)
- [🔄 CI/CD 自动化构建工作流](#-cicd-自动化构建工作流)
- [📄 开源许可](#-开源许可)

---

## 🚀 快速开始与多平台部署

### 1. ⚡ VPS 极速一键安装与管理向导 (置顶推荐)

适用于主流 Linux VPS（Ubuntu / Debian / CentOS 等），一键全自动安装环境、配置 Caddy 反代与申请证书：

```bash
curl -fsSL https://raw.githubusercontent.com/alienmoom/magic-toys/main/setup_caddy.sh -o setup_caddy.sh && chmod +x setup_caddy.sh && sudo ./setup_caddy.sh
```

> 💡 **随时唤醒**：安装后自动注册全局命令 **`toy`**，在终端任意目录输入 **`toy`** 即可呼出交互式管理菜单：
> * Caddy 端口配置与 `h2c`（明文 HTTP/2）内部高效转发
> * Cloudflare Token (DNS-01) / HTTP 80 / 自签证书一键签发与管理
> * 证书路径浅层化存放在 `/etc/caddy/certs/<域名>/`，清晰可查
> * Magic Toys 代理服务按需管理、日志监控与环境清理

---

### 2. 📂 仅允许上传文件部署的平台 (无 Docker / 纯代码环境)

适合 Serv00、各类 Python Web Hosting、虚拟主机或仅支持手动上传代码运行的轻量平台：

1. **上传核心文件**：将项目中的核心文件上传至你的平台工作目录：
   * [`app.py`](file:///c:/Users/Lenovo/Desktop/worker_space/Karing/app.py)（主服务程序）
   * [`index.html`](file:///c:/Users/Lenovo/Desktop/worker_space/Karing/index.html)（Web 主页与伪装面板）
   * [`requirements.txt`](file:///c:/Users/Lenovo/Desktop/worker_space/Karing/requirements.txt)（依赖清单）
2. **安装依赖与启动**：
   ```bash
   pip install -r requirements.txt
   python app.py      # 或 python3 app.py
   ```
3. **在线配置节点**：
   服务启动后，直接在浏览器中打开 **`http(s)://yourdomain.com/settings`**（或对应端口/自定义路径）即可在线管理与配置节点。

---

### 3. 🐳 Docker 与 PaaS 容器平台部署 (Fork 自动构建)

适合 Render、Koyeb、Railway、Hugging Face、Sealos 等 PaaS / Serverless 容器平台或本地 Docker：

#### 方式 A：Fork 本项目通过 GitHub Actions 自动构建镜像
1. 点击仓库右上角 **Fork** 复制到个人账号；
2. 在 Fork 仓库的 **Actions** 中运行构建工作流，自动发布专属镜像至 GHCR；
3. 在容器平台直接填入镜像地址或连接 GitHub 仓库完成部署。

#### 方式 B：本地 Docker / Docker Compose 极速运行
```bash
# 独立单机运行
docker run -d --name magic-toys --restart always -p 3000:3000 \
  -e DIRECT_DOMAIN="你的域名.com" \
  -e NAME="MyNode" \
  ghcr.io/alienmoom/magic-toys:standalone
```

> [!WARNING]
> **非持久化平台数据丢失警告**：
> 在无状态（Stateless）或非持久化容器平台（如 Render / Hugging Face / Koyeb 免费容器）上部署时，容器一旦休眠或重启，本地文件（`config.json`）将会被重置。
> 强烈建议在平台环境变量中配置远程数据库连接（如 `DATABASE_URL=postgres://...` 或 `mysql://...`，配合 `SETTINGS_STORE=database`），对 `/settings` 保存的节点配置数据进行持久化保存。

---

## 🔗 核心访问路径：订阅链接与设置后台

服务启动后，系统的核心 Web 与订阅访问路径如下：

| 功能入口 | URL 地址格式 | 默认完整路径示例 | 用途与说明 |
| :--- | :--- | :--- | :--- |
| 🚀 **订阅链接** | `http(s)://<域名或IP>:<端口>/<SUBLINK_PATH>` | `https://yourdomain.com/sublink` | **标准 v2ray Base64 订阅链接**。<br>复制此链接粘贴到 **Karing** 等客户端中即可一键拉取节点。 |
| 🛠️ **节点管理面板** | `http(s)://<域名或IP>:<端口>/<SETTINGS_PATH>` | `https://yourdomain.com/settings` | **可视化节点配置后台**。<br>在浏览器中在线修改节点名称、协议开关、优选 IP 并持久化保存。 |
| 🌐 **节点展示 Web 主页** | `http(s)://<域名或IP>:<端口>/` | `https://yourdomain.com/` | **前台伪装展示页**（默认深空算力中心主题）。 |

---

## 🌟 功能特性

- **多协议原生支持**：`VLESS`、`Trojan` 与 `Shadowsocks (AEAD 硬件加速)`。
- **丰富的传输层协议**：
  - **WebSocket (WS)**：穿透力强，完美兼容 CDN / Cloudflare。
  - **gRPC (HTTP/2)**：低延迟、高并发传输（内置 h2c 协议优化）。
  - **XHTTP**：新型流传输，支持动态 Padding 与分块传输。
- **多种存储与云端多实例隔离模式**：
  - **单机本地模式**：无需数据库，自动持久化至本地 JSON（`config.json`）。
  - **云端多实例隔离存储**：配置环境变量 `NAME` 与 `DATABASE_URL` 即可开启。多个不同平台/厂商的部署实例（如 `serv00_us`、`koyeb_sg`、`wasmer` 等）共用同一个云数据库，基于 `NAME` 独立隔离读写，互不覆盖。
- **纯 Python 原生零依赖数据库驱动**：内置基于标准 socket 的轻量级 PostgreSQL (支持 SSL/TLS、MD5、SCRAM-SHA-256) 与 MySQL 驱动，无需安装任何第三方二进制库，完美适配 Neon、Supabase、TiDB Cloud、Aiven、RDS 等。
- **可视化后台智能诊断**：
  - **`NAME` 环境变量只读锁定**：通过环境变量注入的节点前缀在 `/settings` 中自动同步并锁定只读，防止误篡改。
  - **一键检测数据库连接**：设置页自带检测按钮，毫秒级异步检测数据库连通性、网络握手与历史配置匹配状态。
- **极致轻量**：极低内存占用（约 20~40MB），完美适配各类架构与小内存 VPS。

---

## ⚙️ 环境变量配置指南 (重点)

### 1. 核心网络与身份标识

| 环境变量 | 类型 | 默认值 | 作用与说明 |
| :--- | :--- | :--- | :--- |
| `APP_KEY` | string | 留空自动生成 | **核心身份 UUID / 鉴权密码**。<br>若留空，服务首次启动时将自动生成全新标准 UUID 并保存至 `config.json`；也可手动指定。 |
| `PORT` | int | `3000` | 内部监听端口。在容器平台通常会自动映射或由平台指定。 |
| `NAME` | string | 空 | **节点名称前缀 / 数据库隔离主键**：<br>• 未配数据库时：作为节点名称前缀，可在 `/settings` 后台自由修改。<br>• 配置 `DATABASE_URL` 时：作为数据库隔离主键，并在 `/settings` 页面自动锁定只读。 |
| `DIRECT_DOMAIN` | string | 空 | **直连域名/公网 IP**。生成订阅链接时作为直连目标地址。 |
| `GATEWAY_DOMAIN` | string | 空 | **套 CDN 域名**。配合 Cloudflare 等 CDN 使用，订阅链接会将 Host/SNI 设为此域名。 |
| `PREFERRED_IP` | string | 空 | **优选 IP/自定义连接地址**。在套 CDN 时，替换节点连接地址为优质 CDN 节点 IP。 |
| `SUBLINK_PATH` | string | `sublink` | 订阅接口访问路径（默认 `/sublink`）。 |
| `SETTINGS_PATH` | string | `settings` | 设置与节点管理后台路径（默认 `/settings`）。 |

### 2. 协议与传输层开关

| 环境变量 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `PROTO_A_ENABLED` | bool | `true` | 是否启用 **VLESS** 协议 (`1`/`true` 开启，`0`/`false` 关闭)。 |
| `PROTO_B_ENABLED` | bool | `true` | 是否启用 **Trojan** 协议。 |
| `PROTO_C_ENABLED` | bool | `true` | 是否启用 **Shadowsocks** 协议。 |
| `CONN_WS_ENABLED` | bool | `true` | 是否启用 **WebSocket (WS)** 传输模式。 |
| `CONN_GRPC_ENABLED`| bool | `false` | 是否启用 **gRPC (HTTP/2)** 传输模式。 |
| `CONN_XHTTP_ENABLED`| bool | `false` | 是否启用 **XHTTP** 传输模式。 |

### 3. 云端数据库与持久化配置 (多实例隔离)

| 环境变量 | 类型 | 默认值 | 详细说明 |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | string | 空 | 数据库连接 URL（支持 **PostgreSQL** 与 **MySQL**）。<br>• PG: `postgresql://user:pass@host:5432/dbname?sslmode=require`<br>• MySQL: `mysql://user:pass@host:3306/dbname`<br>💡 **注意**：只有当**同时配置了 `NAME` 与 `DATABASE_URL`** 时才会启用数据库存储。 |
| `SETTINGS_STORE` | string | 空 (自动识别) | 可选。设为 `database` 或 `db`（通常配置了 `DATABASE_URL` 和 `NAME` 时会自动启用）。 |

#### 💡 云端数据库连接检测与三种状态说明：
在 `/settings` 页面中，`NAME` 输入框右侧设有 **【检测数据库连接】** 按钮，点击将实时反馈：
1. **未完整配置**（缺少 `NAME` 或 `DATABASE_URL`）：提示 `未完整配置环境变量（缺少: ...），连接无法使用。`，此时保持本地模式；
2. **连接成功**：提示 `数据库连接成功（PostgreSQL/MySQL）（已匹配到「xxx」的记录/暂无记录保存时追加）`；
3. **连接失败**：提示 `连接失败，请检查数据库链接是否正确 (错误详情)`，快速排查网络防火墙或密码错误。

### 4. 哪吒监控面板集成 (Nezha)

| 环境变量 | 类型 | 默认值 | 详细说明 |
| :--- | :--- | :--- | :--- |
| `MONITOR_HOST` | string | 空 | **哪吒面板通信域名/IP**（如 `nezha.yourdomain.com`）。 |
| `MONITOR_PORT` | string | 空 | **哪吒面板通信端口**（如 `5555`，标准端口自动开启 TLS）。 |
| `MONITOR_KEY` | string | 空 | **哪吒面板通信密钥 (Agent Key)**。配置后服务启动自动拉起探针。 |

---

## ☁️ Cloudflare CDN 与 NAT VPS 回源配置 (NAT VPS 必看)

绝大多数 NAT VPS 仅有非标高位映射端口（如 `15362`、`33001` 等），无标准 80/443 端口。当为域名开启 Cloudflare CDN 代理（小黄云 ☁️）后，需在 Cloudflare 配置回源规则：

1. **进入规则设置**：登录 Cloudflare 控制台 -> 点击域名 -> **Rules (规则)** -> **Origin Rules (回源规则)** -> 点击 **Create rule**。
2. **设置回源匹配**：
   * **Field** 选择 `Hostname`，**Operator** 选择 `equals`，**Value** 填写套 CDN 的域名（如 `cdn.yourdomain.com`）。
   * **Origin Port (回源端口)**：选择 **Rewrite to... (重写至)**，输入你 NAT VPS 的**真实外部 HTTPS 映射端口**（如 `15362`）。
3. **部署生效**：点击 **Deploy** 保存。
4. **配合优选 IP 使用**：在 `/settings` 后台将 `GATEWAY_DOMAIN` 设为 `cdn.yourdomain.com`，`PREFERRED_IP` 设为优质 CDN 节点 IP，客户端即可直接以标准 `443` 端口连接 CDN 优选节点，并自动转发至你的 NAT VPS。

---

## 📱 客户端订阅导入 (Karing)

1. 打开 **[Karing 客户端](https://github.com/KaringX/karing)**；
2. 进入 **订阅 / Profiles** 页面 -> 点击 **添加 / Add** -> 选择 **通过链接添加 (Add by Link)**；
3. 粘贴订阅地址 `https://yourdomain.com/sublink` 并保存；
4. 客户端将自动解析出全部可用节点，选择节点即可连接。

---

## 🔄 CI/CD 自动化构建工作流

| 工作流文件 | 构建模式 | 说明与产物 |
| :--- | :--- | :--- |
| [docker-build-standalone.yml](.github/workflows/docker-build-standalone.yml) | **独立轻量版 (No-DB)** | 极速单机运行，产物：`ghcr.io/alienmoom/magic-toys:standalone` |
| [docker-build-db.yml](.github/workflows/docker-build-db.yml) | **数据库完整版 (With-DB)** | 包含数据库驱动与依赖，产物：`ghcr.io/alienmoom/magic-toys:db` 与 `:latest` |

---

## 📄 开源许可

本项目遵循 [MIT License](LICENSE) 开源许可协议。
