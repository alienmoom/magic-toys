# Magic Toys 🚀

> **Magic Toys** 是一个基于 **Python** 开发、专为容器、边缘平台（PaaS/Serverless）以及 VPS 设计的轻量级高性能代理协议服务端脚本。
>
> 项目支持 **VLESS** / **Trojan** + **WS** / **gRPC** / **xhttp** 传输协议，以及 **Shadowsocks (SS)** + **WS** 传输协议，原生导出标准 **v2ray Base64** 订阅格式。
>
> 💡 **推荐客户端**：强烈建议使用 **[Karing](https://github.com/KaringX/karing)** 客户端，享受最完整、稳定的多协议及传输层支持。

---

## ⚡ VPS 极速一键安装与管理向导 (置顶推荐)

在你的 Linux VPS（Ubuntu / Debian / CentOS 等主流系统）上以 root 权限运行以下命令，即可一键启动交互式管理向导：

```bash
curl -fsSL https://raw.githubusercontent.com/alienmoom/magic-toys/main/setup_caddy.sh -o setup_caddy.sh && chmod +x setup_caddy.sh && sudo ./setup_caddy.sh
```

> 💡 **随时唤醒**：运行一次后自动注册全局命令 **`toy`**，此后在终端任意目录下直接输入 **`toy`** 即可随时呼出菜单管理服务、配置端口与证书！

<details open>
<summary><b>📺 交互式向导功能一览（点击折叠/展开）</b></summary>

```
====================================================
        Magic Toys · 一键管理向导                   
       (随时输入 toy 即可再次唤醒本向导)          
====================================================
当前对内转发端口: 3000 (h2c 转发至 127.0.0.1)
当前已配域名数量: 2
代理服务运行状态: 运行中 (Active)
----------------------------------------------------
 1. Caddy 端口配置与流量转发 (对内/对外)
 2. 证书与域名管理 (CF Token / HTTP / 自签 / 删除)
 3. 代理脚本配置 (1.安装，2.卸载)
 4. 卸载向导与环境清理 (1.完全卸载，2.保留域名证书卸载)
 5. 查看系统运行状态与实时日志 (Caddy & 代理服务)
 6. 启动 / 停止 / 重启服务
 0. 退出向导
====================================================
```
</details>

---

### 📂 仅允许上传文件部署的平台 (无 Docker / 纯代码运行环境)

适合 Serv00、各类 Python Web Hosting、虚拟主机或仅支持手动上传代码运行的轻量平台：

1. **上传核心文件**：将项目中的核心文件上传至你的平台工作目录：
   * [`app.py`](file:///c:/Users/Lenovo/Desktop/worker_space/Karing/app.py)（主服务程序）
   * [`index.html`](file:///c:/Users/Lenovo/Desktop/worker_space/Karing/index.html)（Web 主页与伪装面板）
   * [`requirements.txt`](file:///c:/Users/Lenovo/Desktop/worker_space/Karing/requirements.txt)（依赖清单）
2. **安装依赖与启动**：
   ```bash
   # 安装依赖
   pip install -r requirements.txt
   
   # 启动服务
   python app.py
   # 或
   python3 app.py
   ```
3. **在线配置节点**：
   服务启动后，直接在浏览器中打开 **`http(s)://yourdomain.com/settings`**（或对应端口/自定义路径）即可在线管理与配置节点信息。

---

### 🐳 Docker 容器平台部署 (Fork 自动构建镜像)

适合 Render、Koyeb、Railway、Hugging Face、Sealos 等支持 Docker 容器镜像部署的 PaaS / Serverless 平台：

1. **Fork 本项目**：点击仓库右上角的 **Fork** 按钮，将本项目复制到你自己的 GitHub 账号下。
2. **启用 GitHub Actions 构建镜像**：
   * 进入你 Fork 后的仓库，切换到 **Actions** 选项卡；
   * 启动对应的构建工作流（如 `Build and Publish Standalone Image` 或 `Build and Publish DB Image`）；
   * GitHub Actions 将自动为你构建出专属的 Docker 容器镜像并发布到 GitHub Packages (GHCR)。
3. **在容器平台部署运行**：
   * 在容器平台新建应用，填入构建好的镜像地址（或直接连接 Fork 的 GitHub 仓库源码构建）；
   * 部署完成后，通过平台分配的域名访问 **`https://yourdomain.com/settings`** 进行节点可视化配置。

> [!WARNING]
> **非持久化平台数据丢失警告**：
> 在无状态（Stateless）或非持久化容器平台（如 Render / Hugging Face / Koyeb 等免费容器实例）上部署时，容器一旦休眠或重启，本地文件（`config.json`）将会被重置。
> 强烈建议在平台环境变量中配置远程数据库连接（如 `DATABASE_URL=postgres://...` 或 `DATABASE_URL=mysql://...`，配合 `SETTINGS_STORE=database`），对 `/settings` 页面保存的节点配置数据进行持久化保存。

---

## 📑 目录

- [⚡ VPS 极速一键安装与管理向导 (置顶推荐)](#-vps-极速一键安装与管理向导-置顶推荐)
  - [📂 仅允许上传文件部署的平台 (无 Docker / 纯代码运行环境)](#-仅允许上传文件部署的平台-无-docker--纯代码运行环境)
  - [🐳 Docker 容器平台部署 (Fork 自动构建镜像)](#-docker-容器平台部署-fork-自动构建镜像)
- [🔗 快速访问：订阅链接与设置管理面板](#-快速访问订阅链接与设置管理面板)
- [功能特性](#-功能特性)
- [环境变量配置指南 (重点)](#-环境变量配置指南-重点)
  - [1. 核心网络与身份标识](#1-核心网络与身份标识)
  - [2. 协议与传输层开关](#2-协议与传输层开关)
  - [3. 数据库与存储配置](#3-数据库与存储配置)
  - [4. 哪吒监控面板集成 (Nezha)](#4-哪吒监控面板集成-nezha-monitoring-agent)
- [多平台部署教程 (重点)](#-多平台部署教程-重点)
  - [一、Docker / Docker Compose 部署](#一docker--docker-compose-部署)
  - [二、VPS 原生 Linux 部署 (Systemd + Caddy + toy 管理向导)](#二vps-原生-linux-部署-systemd--caddy--toy-管理向导)
  - [三、各类 PaaS / 边缘云平台部署](#三各类-paas--边缘云平台部署)
    - [1. Railway](#1-railway)
    - [2. Render / Koyeb](#2-render--koyeb)
    - [3. Serv00 (FreeBSD / 无 Root)](#3-serv00-freebsd--无-root)
    - [4. Hugging Face Spaces](#4-hugging-face-spaces)
  - [四、Cloudflare CDN 套用与非标回源端口配置 (NAT VPS 必看)](#四cloudflare-cdn-套用与非标回源端口配置-nat-vps-必看)
- [客户端订阅导入 (Karing)](#-客户端订阅导入-karing)
- [CI/CD 自动化构建工作流](#-cicd-自动化构建工作流)

---

## 🔗 快速访问：订阅链接与设置管理面板

服务启动后，系统的核心 Web 与订阅访问路径如下（直接位于根路径下）：

| 功能入口 | URL 地址格式 | 默认完整路径示例 | 用途与说明 |
| :--- | :--- | :--- | :--- |
| 🚀 **订阅链接**<br>*(客户端一键导入)* | `http(s)://<域名或IP>:<端口>/<SUBLINK_PATH>` | `https://yourdomain.com/sublink` | **标准 v2ray Base64 订阅链接**。<br>直接复制此链接粘贴到 **Karing** / v2ray 客户端中即可一键拉取全部可用节点。 |
| 🛠️ **订阅配置在线编辑 / 节点管理面板** | `http(s)://<域名或IP>:<端口>/<SETTINGS_PATH>` | `https://yourdomain.com/settings` | **可视化节点配置与设置管理后台**。<br>支持在浏览器中实时修改订阅节点、调整协议规则并持久化保存（支持内存/文件/数据库）。 |
| 🌐 **节点展示 Web 主页** | `http(s)://<域名或IP>:<端口>/` | `https://yourdomain.com/` | **该页面为伪装页面，可让 AI 生成任意主题的页面**（默认内置深空算力中心主题）。 |

> 📌 **注**：`API_PATH`（默认取 UUID 前 8 位）仅用于底层的节点协议传输（如 WebSocket 传输路径、gRPC ServiceName、XHTTP 分块流），**不影响** 上述 HTTP 网页与订阅接口的访问路径。

---

## 🌟 功能特性

- **多协议全支持**：原生支持 `VLESS`、`Trojan` 与 `Shadowsocks (AEAD 硬件加速)`。
- **丰富的传输层协议**：
  - **WebSocket (WS)**：穿透力强，完美兼容 CDN / Cloudflare。
  - **gRPC (HTTP/2)**：低延迟、高并发传输（内置 h2c 协议优化）。
  - **XHTTP**：新型流传输，支持动态 Padding 与分块传输。
- **标准订阅分发**：内置 Web 伪装面板与标准 v2ray Base64 订阅链接分发（接口：`/sublink`）。
- **多种存储模式**：支持纯内存运行、本地 JSON 持久化（`config.json`），以及 **MySQL** / **PostgreSQL** 远程数据库同步。
- **轻量与多架构**：极低内存占用（约 20~40MB），适配 x86_64、ARM64 等各种架构。

---

## ⚙️ 环境变量配置指南 (重点)

你可以通过环境变量灵活定制服务行为：

### 1. 核心网络与身份标识

| 环境变量 | 类型 | 必须/可选 | 默认值 | 作用与说明 |
| :--- | :--- | :--- | :--- | :--- |
| `APP_KEY` | string | 可选 (推荐留空自动生成) | 留空自动生成专属 UUID | **核心身份 UUID / 鉴权密码**。<br>用于客户端连接鉴权（VLESS UUID / Trojan 密码 / SS 密钥源）。**若留空，服务首次启动时将自动生成全新标准 UUID 并持久化保存至 `config.json`**；也可手动指定为专属自定义 UUID。 |
| `PORT` | int | 可选 | `3000` | 内部监听端口。在容器或反向代理后通常设为平台指定的端口（如 `$PORT`）。 |
| `API_PATH` | string | 可选 | 取 `APP_KEY` 前 8 位 | **传输层路径**。用于 WS / gRPC / XHTTP 底层连接路径（如 `/317ad2e2`）。 |
| `SUBLINK_PATH` | string | 可选 | `sublink` | **订阅接口路径**。访问地址为：`/<SUBLINK_PATH>`（默认 `/sublink`，兼容 `FEED_PATH`）。 |
| `NAME` | string | 可选 | 空 | **节点名称前缀**。订阅中节点的名称前缀（如设置 `MyNode` 则为 `MyNode-连接 [VLESS-WS]`）。**可在 `/settings` 后台页面中随时在线修改并保存生效**。 |
| `DIRECT_DOMAIN` | string | 可选 | 空 | **直连域名/公网 IP**。生成订阅链接时作为直接连接的目标地址。 |
| `GATEWAY_DOMAIN` | string | 可选 | 空 | **套 CDN 域名**。配合 Cloudflare 等 CDN 使用，订阅链接会将 Host/SNI 设为此域名。 |
| `PREFERRED_IP` | string | 可选 | 空 | **优选 IP/自定义连接地址**。在套 CDN 时，替换节点连接地址为优质 CDN 节点 IP。 |

### 2. 协议与传输层开关

| 环境变量 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `PROTO_A_ENABLED` | bool | `true` | 是否启用 **VLESS** 协议 (`1`/`true` 开启，`0`/`false` 关闭)。 |
| `PROTO_B_ENABLED` | bool | `true` | 是否启用 **Trojan** 协议。 |
| `PROTO_C_ENABLED` | bool | `true` | 是否启用 **Shadowsocks** 协议。 |
| `CONN_WS_ENABLED` | bool | `true` | 是否启用 **WebSocket (WS)** 传输模式。 |
| `CONN_GRPC_ENABLED`| bool | `false` | 是否启用 **gRPC (HTTP/2)** 传输模式。 |
| `CONN_XHTTP_ENABLED`| bool | `false` | 是否启用 **XHTTP** 传输模式。 |

> 📌 **注**：SS 协议仅支持 WS 传输；VLESS 与 Trojan 可在 WS / gRPC / XHTTP 间选择。

### 3. 数据库与存储配置

| 环境变量 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `SETTINGS_PATH` | string | `settings` | 节点配置与管理页面路径（访问地址：`/<SETTINGS_PATH>`，默认 `/settings`，兼容 `ADVICES_PATH`）。 |
| `SETTINGS_STORE` | string | 空 (内存/文件) | 设为 `database` 或 `db` 时将开启远程数据库存储模式（兼容 `ADVICES_STORE`）。 |
| `DATABASE_URL` | string | 空 | 数据库连接 URL，支持 **MySQL** 与 **PostgreSQL**。<br>• MySQL: `mysql://user:pass@host:3306/dbname`<br>• PostgreSQL: `postgres://user:pass@host:5432/dbname` |
| `DB_TYPE` | string | `mysql` | 数据库类型：`mysql` 或 `postgres`（通常通过 `DATABASE_URL` 自动识别）。 |

### 4. 哪吒监控面板集成 (Nezha Monitoring Agent)

本项目内置了**哪吒监控探针**的自动下载与后台守护功能。配置以下环境变量后，服务启动时将自动识别系统架构（`amd64` / `arm64`）并启动哪吒 Agent，实时向上报主机状态（CPU、内存、网络流量等），完美兼容各类无 Root 权限的 PaaS / 容器 / VPS 环境：

| 环境变量 | 类型 | 默认值 | 详细说明 |
| :--- | :--- | :--- | :--- |
| `MONITOR_HOST` | string | 空 | **哪吒面板通信域名/IP**。<br>• 示例：`nezha.yourdomain.com` 或 `nezha.yourdomain.com:5555` |
| `MONITOR_PORT` | string | 空 | **哪吒面板通信端口**。<br>• 若设置端口（如 `5555` 或 `443`），将按经典命令行参数启动（`443`/`8443`/`2096` 等标准端口自动启用 `--tls`）；<br>• 若留空，则自动启用哪吒 v1 新版 `config.yaml` 模式。 |
| `MONITOR_KEY` | string | 空 | **哪吒面板密钥 (Client Secret / Agent Key)**。<br>在面板添加服务器时生成的通信密钥。 |
| `AUTO_PING` | bool | `0` | 是否启用节点存活自动注册与健康上报（`1`/`true` 开启）。 |

---

## 🚀 多平台部署教程 (重点)

### 一、Docker / Docker Compose 部署

#### 1. 使用预构建镜像直接运行（最快捷）

```bash
# 1. 独立轻量运行（无数据库，单机模式）
docker run -d \
  --name magic-toys \
  --restart always \
  -p 3000:3000 \
  -e APP_KEY="你的自定义-UUID-或保留默认" \
  -e DIRECT_DOMAIN="你的域名.com" \
  -e NAME="MyNode" \
  ghcr.io/alienmoom/magic-toys:standalone

# 2. 包含 MySQL / PostgreSQL 数据库支持运行
docker run -d \
  --name magic-toys \
  --restart always \
  -p 3000:3000 \
  -e APP_KEY="你的自定义-UUID" \
  -e SETTINGS_STORE="database" \
  -e DATABASE_URL="mysql://root:password@1.2.3.4:3306/magic_toys" \
  ghcr.io/alienmoom/magic-toys:db
```

#### 2. 使用 Docker Compose 部署

新建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  magic-toys:
    image: ghcr.io/alienmoom/magic-toys:latest
    container_name: magic-toys
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - PORT=3000
      - APP_KEY=317ad2e2-37e3-42d2-952a-16e636740335
      - DIRECT_DOMAIN=yourdomain.com
      - GATEWAY_DOMAIN=cdn.yourdomain.com
      - NAME=MagicNode
      - PROTO_A_ENABLED=true
      - PROTO_B_ENABLED=true
      - PROTO_C_ENABLED=true
      - CONN_WS_ENABLED=true
```

运行：
```bash
docker compose up -d
```

---

### 二、VPS 原生 Linux 部署 (Systemd + Caddy + toy 管理向导)

适用于 Ubuntu / Debian / CentOS 等主流 VPS。

#### 1. 使用一键全自动向导 (最推荐)

在 VPS 终端直接执行：
```bash
curl -fsSL https://raw.githubusercontent.com/alienmoom/magic-toys/main/setup_caddy.sh -o setup_caddy.sh && chmod +x setup_caddy.sh && sudo ./setup_caddy.sh
```

向导将全自动引导你完成：
- 代理服务安装与后台守护注册
- Caddy 端口配置与 `h2c` 流量反代
- Cloudflare Token / HTTP 80 / 自签三种证书申请与定期自动续期
- 服务运维监控与环境一键卸载

---

#### 2. 手动部署方式 (可选)

```bash
# 1. 安装环境与依赖
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
git clone https://github.com/alienmoom/magic-toys.git /opt/magic-toys
cd /opt/magic-toys
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 2. 配置 Systemd 后台服务守护
sudo tee /etc/systemd/system/magic-toys.service << 'EOF'
[Unit]
Description=Magic Toys Proxy Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/magic-toys
Environment="PORT=3000"
Environment="APP_KEY=317ad2e2-37e3-42d2-952a-16e636740335"
Environment="DIRECT_DOMAIN=yourdomain.com"
Environment="NAME=VPS-Node"
Environment="SUBLINK_PATH=sublink"
Environment="SETTINGS_PATH=settings"
ExecStart=/opt/magic-toys/venv/bin/python3 app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now magic-toys
```

---

#### 3. 配合 Caddy 反向代理与 SSL/TLS 证书配置 (核心推荐)

> [!TIP]
> **💡 为什么本项目强烈推荐并选用 Caddy？**
> 1. **极度轻量与低资源消耗**：Caddy 采用 Go 语言编写，单二进制文件开箱即用，运行内存仅约 **10~20MB**，极其适合 256MB~512MB 的轻量 VPS 或微型容器。
> 2. **原生支持 VPS 内部 `h2c`（明文 HTTP/2）流量反代**：
>    - **这是 gRPC 与 xhttp 能够正常工作的核心前提！**
>    - `gRPC` 与 `xhttp` 强依赖 HTTP/2 的多路复用与双向流式传输能力。传统的 Nginx 默认反代在将外部请求转发给内部应用（`127.0.0.1:3000`）时，**会强制降级为 HTTP/1.1**，导致 gRPC / xhttp 握手失败、0 字节断流或 502 Bad Gateway；
>    - Caddy 原生支持通过 `versions h2c` 直接以明文 HTTP/2 与 `app.py` 通信，完美保留流式多路复用特性。
> 3. **全自动 ACME 证书管理**：Caddy 原生内置全自动证书管理引擎，启动时自动向 Let's Encrypt / ZeroSSL 申请证书并定期自动续期，完全无需外部脚本！

> [!CAUTION]
> **🚨 安全警告：为什么严禁直接使用 80 系明文端口？**
> - **缺乏加密保护**：80 / 8080 等 HTTP 端口是明文传输的，网络流量未经过 TLS 加密保护。
> - **DPI 深度识别与阻断**：明文代理流量极易被运营商（ISP）和防火墙（GFW）通过特征检测和关键字匹配进行实时拦截。
> - **IP / 端口极易被封**：直连使用 80 系端口极易触发防火墙主动探测，短时间内便会导致 VPS IP 或端口被阻断封禁。
> - **最佳实践**：**强烈建议必须通过 Caddy 配置 HTTPS（443 端口或 8443 等高位 TLS 端口）进行全链路加密反向代理**！

---

##### 📁 手动配置参考：标准 `/etc/caddy/Caddyfile` 结构示例

若选择手动配置 Caddy，可直接参考以下标准通用结构（内置 `h2c` 转发宏与三类证书配置样例）：

```caddy
{
	admin off
	auto_https disable_redirects
	log {
		output stdout
		format json
	}
}

# 通用内部 h2c 转发规则 (保持 HTTP/2 流式多路复用，确保 gRPC 与 xhttp 正常)
(proxy_backend) {
	@grpc_ct {
		header Content-Type application/grpc
	}
	@grpc_proxy {
		header X-Grpc-Proxy 1
	}
	handle @grpc_ct {
		reverse_proxy 127.0.0.1:3000 {
			transport http {
				versions h2c
			}
			header_up Host {http.request.host}
		}
	}
	handle @grpc_proxy {
		reverse_proxy 127.0.0.1:3000 {
			transport http {
				versions h2c
			}
			header_up Host {http.request.host}
		}
	}
	handle {
		reverse_proxy 127.0.0.1:3000 {
			header_up Host {http.request.host}
		}
	}
}

# 模式 1：80 端口可用时（ACME HTTP-01 全自动证书）
https://node.yourdomain.com {
	log
	import proxy_backend
}

# 模式 2：80 端口不可用 / NAT VPS（Cloudflare DNS-01 验证，免 80 端口）
https://node.yourdomain.com:8443 {
	tls {
		dns cloudflare {env.CF_API_TOKEN}
	}
	log
	import proxy_backend
}

# 模式 3：套 CDN 域名（本地自签证书 tls internal）
https://cdn.yourdomain.com {
	tls internal
	log
	import proxy_backend
}
```

---

### 三、各类 PaaS / 边缘云平台部署

#### 1. Railway
1. 在 Railway 控制台点击 **New Project** -> **Deploy from GitHub repo**，选择 `magic-toys`。
2. 在 **Variables** 中添加环境变量：
   - `PORT`: `3000` (或留空使用 Railway 自动注入的 PORT)
   - `APP_KEY`: 自定义 UUID
   - `DIRECT_DOMAIN`: 你的 Railway 免费域名（如 `xxx.up.railway.app`）
3. Railway 会自动使用根目录的 `Dockerfile` 构建并完成部署。

#### 2. Render / Koyeb
- **Render**: 选择 **Web Service**，关联仓库，Environment 选择 **Docker**，在 Environment Variables 中填入 `APP_KEY`、`DIRECT_DOMAIN`。
- **Koyeb**: 选择 **GitHub** 部署源，选择 Dockerfile Builder，指定端口为 `3000`，配置环境变量即可。

#### 3. Serv00 (FreeBSD / 无 Root)
在 Serv00 免费虚拟主机上：
1. 在 Serv00 面板中开启 **Run your own applications** 权限，并申请一个 Web 端口（例如 `12345`）。
2. SSH 登录 Serv00：
```bash
cd ~
git clone https://github.com/alienmoom/magic-toys.git
cd magic-toys
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
nohup env PORT=12345 APP_KEY="你的UUID" DIRECT_DOMAIN="你的Serv00域名" ./venv/bin/python3 app.py > app.log 2>&1 &
```

#### 4. Hugging Face Spaces
1. 创建新的 Space，SDK 选择 **Docker**（Blank）。
2. 将本项目代码推送到 HF Space 仓库。
3. 在 Settings -> Variables and secrets 中配置 `APP_KEY` 等参数。

---

### 四、Cloudflare CDN 套用与非标回源端口配置 (NAT VPS 必看)

#### 1. 🚨 为什么 NAT VPS 套 Cloudflare 必须配置回源端口？
- **问题背景**：绝大多数 NAT VPS 只有高位端口映射（如 HTTP 映射为 `15361`、HTTPS 映射为 `15362` 或 `33001` 等），没有标准的 `80` 或 `443` 端口。
- **报错根源**：当你在 Cloudflare DNS 中为域名开启代理（点亮小黄云 ☁️）后，Cloudflare 默认只会尝试回源连接你 VPS 的 `80`（HTTP）或 `443`（HTTPS）端口。由于 NAT VPS 没有开放这两个端口，将直接导致 **`Error 521: Web server is down`** 或 **`Error 522: Connection timed out`** 错误。
- **解决方案**：必须在 Cloudflare 控制台添加 **Origin Rules（回源规则）**，显式告诉 Cloudflare 回源到你 VPS 的实际非标映射端口！

---

#### 2. 🛠️ Cloudflare Origin Rules (回源规则) 设置四步法

1. **登录 Cloudflare 控制台**：
   - 进入你的域名管理后台，在左侧导航栏依次展开 **Rules (规则)** -> 点击 **Origin Rules (回源规则)**。
2. **创建规则**：
   - 点击 **Create rule (创建规则)**，输入规则名称（例如：`nat-vps-origin-port`）。
3. **设置匹配条件与回源端口**：
   - **When incoming requests match (匹配条件)**：
     - **Field (字段)**：选择 `Hostname (主机名)`
     - **Operator (运算符)**：选择 `equals (等于)`
     - **Value (值)**：输入你的套 CDN 域名（例如：`cdn.yourdomain.com`）
   - **Origin Port (回源端口)**：
     - 选择 **Rewrite to... (重写至...)**
     - **Port (端口号)**：输入你 NAT VPS 的**真实外部 HTTP/HTTPS 映射端口**（例如：`15361` 或 `33001`）。
4. **保存生效**：
   - 点击底部的 **Deploy (部署)** 按钮即可立即生效！

---

#### 3. 💡 搭配优选 IP 与环境变量使用建议

在配置好 Cloudflare 回源端口后，可将服务环境变量配置为：
- `GATEWAY_DOMAIN`：设置为你的套 CDN 域名（如 `cdn.yourdomain.com`），订阅链接会自动将 SNI / Host 标头设置为此域名。
- `PREFERRED_IP`：设置为本地测速筛选出的优质 Cloudflare CDN 优选节点 IP（如香港、日本、美国优选 CDN 节点）。

**最终效果**：
- 客户端直接以标准端口（如 `443`）连接速度最快的 Cloudflare 优选 IP；
- Cloudflare CDN 接收请求后，自动通过 Origin Rules 转发到你 NAT VPS 的真实非标端口；
- **全流程无需在客户端手动输入复杂的非标端口，且完美隐藏源站真实 IP、有效防御阻断与扫描！**

---

## 📱 客户端订阅导入 (Karing)

本项目输出标准的 **v2ray Base64** 订阅协议格式。

### 1. 获取订阅链接
启动服务后，订阅地址格式为：
```
http(s)://<你的服务器域名或IP>:<端口>/<SUBLINK_PATH>
```
> 默认示例：`https://yourdomain.com/sublink`

### 2. 在 Karing 中使用
1. 打开 **[Karing 客户端](https://github.com/KaringX/karing)**。
2. 进入 **订阅 / Profiles** 页面 -> 点击 **添加 / Add**。
3. 选择 **通过链接添加 (Add by Link)**，粘贴上述订阅地址并保存。
4. 客户端将自动解析出包含 VLESS、Trojan、Shadowsocks 的节点列表，选择节点即可连接！

---

## 🔄 CI/CD 自动化构建工作流

本项目通过 GitHub Actions 提供了两个开箱即用的自动化镜像构建工作流：

| 工作流文件 | 构建模式 | 说明与适用场景 |
| :--- | :--- | :--- |
| [docker-build-standalone.yml](.github/workflows/docker-build-standalone.yml) | **独立轻量版 (No-DB)** | 适用于单机极速部署。镜像在无数据库依赖下运行，验证单机健康后自动发布至 `ghcr.io/alienmoom/magic-toys:standalone`。 |
| [docker-build-db.yml](.github/workflows/docker-build-db.yml) | **数据库完整版 (With-DB)** | 包含 MySQL CI 服务容器联调测试，注入数据库连接环境变量，自动完成表结构验证并发布至 `ghcr.io/alienmoom/magic-toys:db` 与 `:latest`。 |

---

## 📄 开源许可

本项目遵循 MIT 开源许可协议。
