#!/usr/bin/env bash
# ==============================================================================
# Magic Toys · Caddy & 代理服务一键管理向导 (快捷命令: toy)
# 支持：端口自定义、流量转发(h2c)、CF Token/HTTP/自签证书申请与删除管理、
#       代理服务安装与卸载、脚本与环境完全卸载/保留证书卸载
# ==============================================================================

set -e

CADDY_FILE="/etc/caddy/Caddyfile"
CONF_DIR="/etc/caddy"
ENV_OVERRIDE="/etc/systemd/system/caddy.service.d/override.conf"
CERT_DIR="/var/lib/caddy/.local/share/caddy/certificates"
SCRIPT_PATH="$(readlink -f "$0")"
APP_DIR="/opt/magic-toys"
SERVICE_FILE="/etc/systemd/system/magic-toys.service"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
PLAIN='\033[0m'

# 检查 Root 权限
check_root() {
    if [ "$(id -u)" != "0" ]; then
        echo -e "${RED}[错误] 本脚本必须以 root 权限运行！请使用 sudo bash $0${PLAIN}"
        exit 1
    fi
}

# 注册全局快捷命令 toy
install_toy_alias() {
    if [ "$SCRIPT_PATH" != "/usr/local/bin/toy" ]; then
        cp "$SCRIPT_PATH" /usr/local/bin/toy
        chmod +x /usr/local/bin/toy
    fi
}

# 检查并安装基础依赖与 Caddy
ensure_caddy_installed() {
    if ! command -v caddy &> /dev/null; then
        echo -e "${YELLOW}>>> 未检测到 Caddy，正在为您自动安装...${PLAIN}"
        if command -v apt &> /dev/null; then
            apt update && apt install -y debian-keyring debian-archive-keyring apt-transport-https curl sudo gpg gnupg
            curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
            curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
            apt update && apt install -y caddy
        elif command -v dnf &> /dev/null; then
            dnf install -y 'dnf-command(copr)'
            dnf copr enable -y @caddy/caddy
            dnf install -y caddy
        else
            echo -e "${RED}[错误] 不支持的 Linux 发行版，请手动安装 Caddy！${PLAIN}"
            exit 1
        fi
        systemctl enable caddy
    fi
    mkdir -p "$CONF_DIR"
    ensure_base_caddyfile
}

# 安装包含 Cloudflare DNS 插件的 Caddy
install_caddy_cf_plugin() {
    if command -v caddy &> /dev/null && caddy list-modules 2>/dev/null | grep -q "dns.providers.cloudflare"; then
        echo -e "${GREEN}✔ 检测到 Caddy 已集成 Cloudflare DNS 插件，跳过安装。${PLAIN}"
        return 0
    fi

    echo -e "${CYAN}>>> 正在准备集成 Cloudflare DNS 插件的 Caddy 二进制...${PLAIN}"
    local arch="$(uname -m)"
    local caddy_arch="amd64"
    case "$arch" in
        x86_64) caddy_arch="amd64" ;;
        aarch64|arm64) caddy_arch="arm64" ;;
        armv7l) caddy_arch="armv7" ;;
        s390x) caddy_arch="s390x" ;;
        riscv64) caddy_arch="riscv64" ;;
        *) caddy_arch="$arch" ;;
    esac

    local downloaded=false
    echo -e "${YELLOW}>>> 正在从 Caddy 官方 API 下载支持 Cloudflare DNS 插件的二进制 (${caddy_arch})...${PLAIN}"
    if curl -sLf "https://caddyserver.com/api/download?os=linux&arch=${caddy_arch}&p=github.com%2Fcaddy-dns%2Fcloudflare" -o /tmp/caddy_cf; then
        chmod +x /tmp/caddy_cf
        if /tmp/caddy_cf list-modules 2>/dev/null | grep -q "dns.providers.cloudflare"; then
            systemctl stop caddy 2>/dev/null || true
            cp /tmp/caddy_cf /usr/bin/caddy
            chmod +x /usr/bin/caddy
            setcap 'cap_net_bind_service=+ep' /usr/bin/caddy 2>/dev/null || true
            rm -f /tmp/caddy_cf
            downloaded=true
            echo -e "${GREEN}>>> Cloudflare 插件版 Caddy 下载安装完成！${PLAIN}"
        fi
    fi

    if [ "$downloaded" = false ]; then
        echo -e "${YELLOW}>>> 官方预编译 API 下载未完成，尝试使用 xcaddy 进行本地构建...${PLAIN}"
        if command -v apt &> /dev/null; then
            apt update && apt install -y golang-go curl git
        elif command -v dnf &> /dev/null; then
            dnf install -y golang curl git
        fi
        if ! command -v xcaddy &> /dev/null; then
            go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest
            export PATH=$PATH:$(go env GOPATH)/bin:/root/go/bin
        fi
        xcaddy build --with github.com/caddy-dns/cloudflare
        systemctl stop caddy 2>/dev/null || true
        mv ./caddy /usr/bin/caddy
        setcap 'cap_net_bind_service=+ep' /usr/bin/caddy 2>/dev/null || true
        echo -e "${GREEN}>>> Cloudflare 插件版 Caddy 编译替换完成！${PLAIN}"
    fi
}

# 初始化基础 Caddyfile 架构
ensure_base_caddyfile() {
    if [ ! -f "$CADDY_FILE" ]; then
        cat > "$CADDY_FILE" << 'EOF'
{
	admin off
	auto_https disable_redirects
	log {
		output stdout
		format json
	}
}

# ==============================================================================
# 通用内部 h2c 转发规则 (保持 HTTP/2 流式，确保 gRPC 与 xhttp 正常)
# ==============================================================================
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
EOF
    fi
}

# 获取当前对内转发端口（默认3000）
get_backend_port() {
    if [ -f "$CADDY_FILE" ]; then
        local port=$(grep -oE "reverse_proxy 127.0.0.1:[0-9]+" "$CADDY_FILE" | head -n 1 | awk -F':' '{print $2}')
        echo "${port:-3000}"
    else
        echo "3000"
    fi
}

# 获取已配置的站点与端口信息 (每行格式: domain:port)
get_configured_sites_info() {
    if [ -f "$CADDY_FILE" ]; then
        python3 -c "
import re
try:
    with open('$CADDY_FILE', 'r') as f:
        content = f.read()
    matches = re.findall(r'https?://([A-Za-z0-9.-]+)(?::([0-9]+))?\s*\{', content)
    for d, p in matches:
        print(f'{d}:{p if p else 443}')
except Exception:
    pass
"
    fi
}

# 获取当前所有已配置的域名列表
get_configured_domains() {
    if [ -f "$CADDY_FILE" ]; then
        grep -E "^https?://" "$CADDY_FILE" | awk '{print $1}' | sed 's|https://||g; s|http://||g; s|{||g; s|}||g'
    fi
}

# 获取已配置域名及对应证书类型 (每行格式: domain|cert_type)
get_configured_domains_with_cert_type() {
    if [ -f "$CADDY_FILE" ]; then
        python3 -c "
import re
try:
    with open('$CADDY_FILE', 'r') as f:
        content = f.read()
    blocks = re.findall(r'(https?://([A-Za-z0-9.-]+)(?::([0-9]+))?\s*\{([^}]*)\})', content, re.DOTALL)
    for full_match, domain, port, body in blocks:
        body_lower = body.lower()
        if 'tls internal' in body_lower:
            cert_type = '自签证书'
        elif 'dns cloudflare' in body_lower:
            cert_type = 'acme证书'
        elif re.search(r'tls\s+/\S+\s+/\S+', body):
            cert_type = '自签证书'
        else:
            cert_type = 'acme证书'
        display_domain = f'{domain}:{port}' if port and port != '443' else domain
        print(f'{display_domain}|{cert_type}')
except Exception:
    pass
"
    fi
}

# 获取当前所有对外监听端口汇总（例如 443, 8443）
get_listen_ports_summary() {
    if [ -f "$CADDY_FILE" ]; then
        python3 -c "
import re
try:
    with open('$CADDY_FILE', 'r') as f:
        content = f.read()
    matches = re.findall(r'https?://[A-Za-z0-9.-]+(?::([0-9]+))?\s*\{', content)
    ports = sorted(list(set([p if p else '443' for p in matches])), key=lambda x: int(x) if x.isdigit() else 0)
    print(', '.join(ports) if ports else '443')
except Exception:
    print('443')
"
    else
        echo "443"
    fi
}

# 获取当前 Caddy 统一监听端口 (若配置了自定义端口则返回该端口，默认 443)
get_caddy_listen_port() {
    if [ -f "$CADDY_FILE" ]; then
        python3 -c "
import re
try:
    with open('$CADDY_FILE', 'r') as f:
        content = f.read()
    match = re.search(r'https?://[A-Za-z0-9.-]+:([0-9]+)\s*\{', content)
    if match:
        print(match.group(1))
    else:
        print('443')
except Exception:
    print('443')
"
    else
        echo "443"
    fi
}

# 获取代理服务运行状态
get_app_service_status() {
    if systemctl is-active --quiet magic-toys 2>/dev/null; then
        echo -e "${GREEN}运行中 (Active)${PLAIN}"
    elif [ -f "$SERVICE_FILE" ]; then
        echo -e "${YELLOW}已停止 (Stopped)${PLAIN}"
    else
        echo -e "${RED}未安装 (Not Installed)${PLAIN}"
    fi
}

# 重载 Caddy 服务
reload_caddy() {
    echo -e "${YELLOW}>>> 正在验证 Caddyfile 语法并重启服务...${PLAIN}"
    if [ -f "$ENV_OVERRIDE" ]; then
        local env_var=$(grep 'Environment=' "$ENV_OVERRIDE" | sed 's/Environment="//;s/"$//')
        [ -n "$env_var" ] && export "$env_var" 2>/dev/null || true
    fi
    if caddy validate --config "$CADDY_FILE"; then
        systemctl daemon-reload
        systemctl enable --now caddy
        systemctl restart caddy
        echo -e "${GREEN}✔ Caddy 配置已平滑重启生效！${PLAIN}"
    else
        echo -e "${RED}✖ Caddyfile 语法验证失败，请检查配置文件！${PLAIN}"
    fi
}

# ==============================================================================
# 模块 1：Caddy 端口配置与流量转发 (对内/对外)
# ==============================================================================
configure_ports_and_proxy() {
    while true; do
        clear
        echo -e "${CYAN}====================================================${PLAIN}"
        echo -e "${CYAN}    1. Caddy 端口配置与流量转发 (对内/对外)          ${PLAIN}"
        echo -e "${CYAN}====================================================${PLAIN}"

        local current_listen=$(get_listen_ports_summary)
        local current_backend=$(get_backend_port)
        echo -e "当前【Caddy监听端口】: ${GREEN}${current_listen}${PLAIN}"
        echo -e "当前【内部转发端口】  : ${GREEN}${current_backend}${PLAIN} (h2c 转发至 127.0.0.1:${current_backend})"

        echo -e "\n${YELLOW}说明：${PLAIN}"
        echo -e "• 【Caddy监听端口】：默认为443，可修改为其它端口，需确认托管在Caddy中的域名流量能打到该端口即可。"
        echo -e "• 【内部转发端口】：本地代理程序 (app.py) 监听的内部端口（默认为 3000）。\n"

        echo -e "----------------------------------------------------"
        echo -e " ${GREEN}1.${PLAIN} Caddy 监听端口设置"
        echo -e " ${GREEN}2.${PLAIN} 内部转发端口设置"
        echo -e " ${BLUE}0.${PLAIN} 返回主菜单"
        echo -e "===================================================="
        read -rp "请输入选项 [0-2]: " port_choice

        case "$port_choice" in
            1)
                set_caddy_listen_port
                ;;
            2)
                set_backend_proxy_port
                ;;
            0)
                break
                ;;
            *)
                echo -e "${RED}输入无效，请重新输入！${PLAIN}"
                sleep 1
                ;;
        esac
    done
}

# 1.1 Caddy 监听端口设置
set_caddy_listen_port() {
    clear
    echo -e "${CYAN}>>> 1. Caddy 监听端口设置${PLAIN}"
    echo -e "${YELLOW}提示：默认为 443，可修改为其它端口，需确认托管在 Caddy 中的域名流量能打到该端口即可。${PLAIN}\n"

    local site_list=($(get_configured_sites_info))
    if [ ${#site_list[@]} -gt 0 ]; then
        echo -e "当前已配置的域名及其监听端口："
        for idx in "${!site_list[@]}"; do
            local s_dom=$(echo "${site_list[$idx]}" | awk -F':' '{print $1}')
            local s_port=$(echo "${site_list[$idx]}" | awk -F':' '{print $2}')
            echo -e "  • ${CYAN}${s_dom}${PLAIN} (当前监听端口: ${GREEN}${s_port}${PLAIN})"
        done
        echo -e ""
    fi

    read -rp "请输入新的【Caddy监听端口】(回车默认 443，NAT VPS 请输入映射端口如 8443, 15362): " new_port
    new_port=${new_port:-443}

    if ! [[ "$new_port" =~ ^[0-9]+$ ]] || [ "$new_port" -lt 1 ] || [ "$new_port" -gt 65535 ]; then
        echo -e "${RED}端口必须为 1-65535 之间的有效数字！${PLAIN}"
        read -rp "按回车键返回..."
        return
    fi

    if [ ${#site_list[@]} -gt 0 ]; then
        python3 -c "
import re
new_p = '$new_port'
cfile = '$CADDY_FILE'
try:
    with open(cfile, 'r') as f:
        content = f.read()
    def repl(m):
        prefix = m.group(1)
        domain = m.group(2)
        suffix = m.group(3)
        if str(new_p) == '443':
            return f'{prefix}{domain}{suffix}'
        else:
            return f'{prefix}{domain}:{new_p}{suffix}'
    new_content = re.sub(r'(https?://)([A-Za-z0-9.-]+)(?::[0-9]+)?(\s*\{)', repl, content)
    with open(cfile, 'w') as f:
        f.write(new_content)
    print('OK')
except Exception as e:
    print('ERROR:', e)
"
        reload_caddy
        echo -e "${GREEN}✔ 已将所有托管域名的 Caddy 监听端口更新为：${new_port}${PLAIN}"
    else
        echo -e "${YELLOW}当前暂无配置的域名，请在【模块 2】中添加域名时指定端口 ${new_port}。${PLAIN}"
    fi
    read -rp "按回车键继续..."
}

# 1.2 内部转发端口设置
set_backend_proxy_port() {
    clear
    echo -e "${CYAN}>>> 2. 内部转发端口设置${PLAIN}"
    local current_backend=$(get_backend_port)
    echo -e "当前【内部转发端口】: ${GREEN}${current_backend}${PLAIN} (Caddy 将流量通过 h2c 转发至 127.0.0.1:${current_backend})"
    echo -e "说明：此端口应与本地代理程序 (app.py) 监听的内部端口保持一致（默认为 3000）。\n"

    read -rp "请输入新的【内部转发端口】(直接回车保持 ${current_backend}): " new_backend
    new_backend=${new_backend:-$current_backend}

    if ! [[ "$new_backend" =~ ^[0-9]+$ ]] || [ "$new_backend" -lt 1 ] || [ "$new_backend" -gt 65535 ]; then
        echo -e "${RED}端口必须为 1-65535 之间的有效数字！${PLAIN}"
        read -rp "按回车键返回..."
        return
    fi

    if [ "$new_backend" != "$current_backend" ]; then
        python3 -c "
import re
new_b = '$new_backend'
cfile = '$CADDY_FILE'
try:
    with open(cfile, 'r') as f:
        content = f.read()
    new_content = re.sub(r'reverse_proxy 127\.0\.0\.1:[0-9]+', f'reverse_proxy 127.0.0.1:{new_b}', content)
    with open(cfile, 'w') as f:
        f.write(new_content)
    print('OK')
except Exception as e:
    print('ERROR:', e)
"
        reload_caddy
        echo -e "${GREEN}✔ 已将内部转发端口更新为：${new_backend}${PLAIN}"
        echo -e "${YELLOW}提示：如果 Magic Toys 代理服务正在运行，请前往【模块 3】重新配置/更新服务的 PORT 参数以保持一致。${PLAIN}"
    else
        echo -e "${YELLOW}端口未做变更。${PLAIN}"
    fi
    read -rp "按回车键继续..."
}

# ==============================================================================
# 模块 2：证书管理 (CF Token 申请 / HTTP 申请 / 自签证书 / 证书删除)
# ==============================================================================
manage_certificates() {
    while true; do
        clear
        echo -e "${CYAN}====================================================${PLAIN}"
        echo -e "${CYAN}    2. 证书与域名管理 (申请 / 自签 / 删除)           ${PLAIN}"
        echo -e "${CYAN}====================================================${PLAIN}"
        echo -e "当前已配置的域名清单："
        local domains_raw=$(get_configured_domains_with_cert_type)
        local domains=($domains_raw)
        if [ ${#domains[@]} -eq 0 ]; then
            echo -e "  ${YELLOW}(暂无配置域名)${PLAIN}"
        else
            for idx in "${!domains[@]}"; do
                local d_name=$(echo "${domains[$idx]}" | awk -F'|' '{print $1}')
                local d_cert=$(echo "${domains[$idx]}" | awk -F'|' '{print $2}')
                echo -e "  [${GREEN}$((idx+1))${PLAIN}] ${CYAN}${d_name}${PLAIN}  ${YELLOW}(${d_cert})${PLAIN}"
            done
        fi
        echo -e "----------------------------------------------------"
        echo -e " 1. Cloudflare Token 申请证书 ${GREEN}(推荐，DNS-01，免 80 端口)${PLAIN}"
        echo -e " 2. HTTP 申请证书 ${YELLOW}(需 80 端口正常开放，HTTP-01)${PLAIN}"
        echo -e " 3. 生成 Caddy 自签证书 ${BLUE}(tls internal，本地自签)${PLAIN}"
        echo -e " 4. 证书与域名删除管理 ${RED}(列出并删除已有域名及证书)${PLAIN}"
        echo -e " 0. 返回主菜单"
        echo -e "===================================================="
        read -rp "请输入选项 [0-4]: " cert_choice

        case "$cert_choice" in
            1)
                add_domain_cf_token
                ;;
            2)
                add_domain_http80
                ;;
            3)
                add_domain_self_signed
                ;;
            4)
                delete_domain_certificate
                ;;
            0)
                break
                ;;
            *)
                echo -e "${RED}输入无效，请重新输入！${PLAIN}"
                sleep 1
                ;;
        esac
    done
}

# 2.1 Cloudflare Token 申请证书 (DNS-01)
add_domain_cf_token() {
    clear
    echo -e "${CYAN}>>> 1. Cloudflare Token 自动申请证书 (DNS-01 验证)${PLAIN}"
    echo -e "适合：80 端口被封禁的 VPS、NAT VPS、或希望免 80 端口全自动签发证书的环境。\n"

    read -rp "请输入要配置的域名 (例如 node.yourdomain.com 或 cdn.yourdomain.com): " domain
    if [ -z "$domain" ]; then
        echo -e "${RED}域名不能为空！${PLAIN}"
        sleep 1
        return
    fi

    local port=$(get_caddy_listen_port)

    read -rp "请输入【Cloudflare DNS API Token】: " cf_token
    if [ -z "$cf_token" ]; then
        echo -e "${RED}Cloudflare Token 不能为空！${PLAIN}"
        sleep 1
        return
    fi

    install_caddy_cf_plugin

    mkdir -p /etc/systemd/system/caddy.service.d
    cat > "$ENV_OVERRIDE" << EOF
[Service]
Environment="CF_API_TOKEN=${cf_token}"
EOF

    remove_domain_from_caddyfile "$domain"

    if [ "$port" = "443" ]; then
        cat >> "$CADDY_FILE" << EOF

https://${domain} {
	tls {
		dns cloudflare {env.CF_API_TOKEN}
	}
	log
	import proxy_backend
}
EOF
    else
        cat >> "$CADDY_FILE" << EOF

https://${domain}:${port} {
	tls {
		dns cloudflare {env.CF_API_TOKEN}
	}
	log
	import proxy_backend
}
EOF
    fi

    reload_caddy
    if [ "$port" = "443" ]; then
        echo -e "${GREEN}✔ 域名 https://${domain} (Cloudflare DNS-01) 已成功添加并生效！${PLAIN}"
    else
        echo -e "${GREEN}✔ 域名 https://${domain}:${port} (Cloudflare DNS-01) 已成功添加并生效 (自动跟随当前 Caddy 监听端口 ${port})！${PLAIN}"
    fi
    read -rp "按回车键继续..."
}

# 2.2 HTTP 申请证书 (HTTP-01)
add_domain_http80() {
    clear
    echo -e "${CYAN}>>> 2. HTTP 80 端口自动申请证书 (HTTP-01 验证)${PLAIN}"
    echo -e "适合：80 与 443 端口正常开放的标准独立 VPS。\n"

    read -rp "请输入要配置的域名 (例如 node.yourdomain.com): " domain
    if [ -z "$domain" ]; then
        echo -e "${RED}域名不能为空！${PLAIN}"
        sleep 1
        return
    fi

    local port=$(get_caddy_listen_port)

    remove_domain_from_caddyfile "$domain"

    if [ "$port" = "443" ]; then
        cat >> "$CADDY_FILE" << EOF

https://${domain} {
	log
	import proxy_backend
}
EOF
    else
        cat >> "$CADDY_FILE" << EOF

https://${domain}:${port} {
	log
	import proxy_backend
}
EOF
    fi

    reload_caddy
    if [ "$port" = "443" ]; then
        echo -e "${GREEN}✔ 域名 https://${domain} (HTTP-01 自动申请) 已成功添加！${PLAIN}"
    else
        echo -e "${GREEN}✔ 域名 https://${domain}:${port} (HTTP-01 自动申请) 已成功添加 (自动跟随当前 Caddy 监听端口 ${port})！${PLAIN}"
    fi
    read -rp "按回车键继续..."
}

# 2.3 自签证书 (tls internal)
add_domain_self_signed() {
    clear
    echo -e "${CYAN}>>> 3. 生成 Caddy 本地自签证书 (tls internal)${PLAIN}"
    echo -e "适合：配合 Cloudflare Full 模式套 CDN、或内网/测试节点。\n"

    read -rp "请输入要配置的域名 (例如 cdn.yourdomain.com): " domain
    if [ -z "$domain" ]; then
        echo -e "${RED}域名不能为空！${PLAIN}"
        sleep 1
        return
    fi

    local port=$(get_caddy_listen_port)

    remove_domain_from_caddyfile "$domain"

    if [ "$port" = "443" ]; then
        cat >> "$CADDY_FILE" << EOF

https://${domain} {
	tls internal
	log
	import proxy_backend
}
EOF
    else
        cat >> "$CADDY_FILE" << EOF

https://${domain}:${port} {
	tls internal
	log
	import proxy_backend
}
EOF
    fi

    reload_caddy
    if [ "$port" = "443" ]; then
        echo -e "${GREEN}✔ 域名 https://${domain} (自签证书 tls internal) 已成功添加！${PLAIN}"
    else
        echo -e "${GREEN}✔ 域名 https://${domain}:${port} (自签证书 tls internal) 已成功添加 (自动跟随当前 Caddy 监听端口 ${port})！${PLAIN}"
    fi
    read -rp "按回车键继续..."
}

# 从 Caddyfile 中安全移除某个域名配置块
remove_domain_from_caddyfile() {
    local target="$1"
    python3 -c "
import sys, re
target = '$target'
caddy_file = '$CADDY_FILE'
try:
    with open(caddy_file, 'r') as f:
        content = f.read()
    pattern = r'\n?https?://' + re.escape(target) + r'(:[0-9]+)?\s*\{[^}]*\}'
    new_content = re.sub(pattern, '', content)
    with open(caddy_file, 'w') as f:
        f.write(new_content)
except Exception as e:
    pass
"
}

# 2.4 证书与域名删除管理
delete_domain_certificate() {
    clear
    echo -e "${CYAN}====================================================${PLAIN}"
    echo -e "${CYAN}    证书与域名删除管理                              ${PLAIN}"
    echo -e "${CYAN}====================================================${PLAIN}"

    local domains_raw=$(get_configured_domains_with_cert_type)
    local domains=($domains_raw)
    if [ ${#domains[@]} -eq 0 ]; then
        echo -e "${YELLOW}当前没有任何配置的域名！${PLAIN}"
        read -rp "按回车键返回..."
        return
    fi

    echo -e "当前已配置的域名列表："
    for idx in "${!domains[@]}"; do
        local d_name=$(echo "${domains[$idx]}" | awk -F'|' '{print $1}')
        local d_cert=$(echo "${domains[$idx]}" | awk -F'|' '{print $2}')
        echo -e "  [${GREEN}$((idx+1))${PLAIN}] ${CYAN}${d_name}${PLAIN}  ${YELLOW}(${d_cert})${PLAIN}"
    done
    echo -e "  [${RED}0${PLAIN}] 返回上级菜单"
    echo -e "----------------------------------------------------"

    read -rp "请选择要删除的域名序号 [0-${#domains[@]}]: " del_idx

    if [ "$del_idx" = "0" ] || [ -z "$del_idx" ]; then
        return
    fi

    if ! [[ "$del_idx" =~ ^[0-9]+$ ]] || [ "$del_idx" -lt 1 ] || [ "$del_idx" -gt "${#domains[@]}" ]; then
        echo -e "${RED}输入无效！${PLAIN}"
        sleep 1
        return
    fi

    local selected_entry="${domains[$((del_idx-1))]}"
    local selected_domain=$(echo "$selected_entry" | awk -F'|' '{print $1}')
    local clean_domain=$(echo "$selected_domain" | awk -F':' '{print $1}')

    read -rp "确认要彻底删除域名 [${selected_domain}] 及其证书配置吗？(y/n): " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        remove_domain_from_caddyfile "$selected_domain"
        rm -rf "${CERT_DIR}"/*"${clean_domain}"* 2>/dev/null || true
        reload_caddy
        echo -e "${GREEN}✔ 域名 [${selected_domain}] 及其证书已成功删除！${PLAIN}"
    else
        echo -e "${YELLOW}操作已取消。${PLAIN}"
    fi
    read -rp "按回车键继续..."
}

# ==============================================================================
# 模块 3：代理脚本配置 (1.安装，2.卸载)
# ==============================================================================
manage_proxy_app() {
    while true; do
        clear
        echo -e "${CYAN}====================================================${PLAIN}"
        echo -e "${CYAN}    3. 代理脚本配置 (Magic Toys 代理服务管理)        ${PLAIN}"
        echo -e "${CYAN}====================================================${PLAIN}"
        echo -e "当前代理服务状态: $(get_app_service_status)"
        echo -e "----------------------------------------------------"
        echo -e " ${GREEN}1.${PLAIN} 安装 / 重新配置代理服务 (Magic Toys)"
        echo -e " ${RED}2.${PLAIN} 卸载代理服务 (停止并移除守护服务)"
        echo -e " ${BLUE}0.${PLAIN} 返回主菜单"
        echo -e "===================================================="
        read -rp "请输入选项 [0-2]: " app_choice

        case "$app_choice" in
            1)
                install_proxy_app
                ;;
            2)
                uninstall_proxy_app
                ;;
            0)
                break
                ;;
            *)
                echo -e "${RED}输入无效，请重新输入！${PLAIN}"
                sleep 1
                ;;
        esac
    done
}

# 3.1 安装 / 配置代理服务
install_proxy_app() {
    clear
    echo -e "${CYAN}====================================================${PLAIN}"
    echo -e "${CYAN}    安装 / 重新配置 Magic Toys 代理服务              ${PLAIN}"
    echo -e "${CYAN}====================================================${PLAIN}"

    echo -e "${YELLOW}>>> 正在检查系统依赖 (Python3, pip, venv, git)...${PLAIN}"
    if command -v apt &> /dev/null; then
        apt update && apt install -y python3 python3-pip python3-venv git curl
    elif command -v dnf &> /dev/null; then
        dnf install -y python3 python3-pip git curl
    elif command -v yum &> /dev/null; then
        yum install -y python3 python3-pip git curl
    fi

    # 准备项目代码目录
    if [ ! -f "$APP_DIR/app.py" ]; then
        # 如果当前脚本所在目录下有 app.py，直接复制
        local script_dir="$(dirname "$SCRIPT_PATH")"
        if [ -f "$script_dir/app.py" ]; then
            echo -e "${YELLOW}>>> 正在从本地目录部署至 ${APP_DIR}...${PLAIN}"
            mkdir -p "$APP_DIR"
            cp -rf "$script_dir"/* "$APP_DIR/"
        else
            echo -e "${YELLOW}>>> 正在从 GitHub 克隆最新 Magic Toys 仓库...${PLAIN}"
            git clone https://github.com/alienmoom/magic-toys.git "$APP_DIR"
        fi
    fi

    # 创建虚拟环境并安装依赖
    echo -e "${YELLOW}>>> 正在初始化 Python 虚拟环境与安装依赖...${PLAIN}"
    cd "$APP_DIR"
    if [ ! -d "$APP_DIR/venv" ]; then
        python3 -m venv "$APP_DIR/venv"
    fi
    "$APP_DIR/venv/bin/pip" install --upgrade pip
    if [ -f "$APP_DIR/requirements.txt" ]; then
        "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
    fi

    # 交互式收集环境变量
    echo -e "\n${CYAN}>>> 配置服务运行参数：${PLAIN}"
    local default_uuid="$("$APP_DIR/venv/bin/python3" -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || echo '317ad2e2-37e3-42d2-952a-16e636740335')"
    read -rp "请输入核心 UUID [APP_KEY] (回车自动生成: ${default_uuid}): " app_key
    app_key=${app_key:-$default_uuid}

    local current_port=$(get_backend_port)
    read -rp "请输入服务监听端口 [PORT] (回车默认与 Caddy 对齐: ${current_port}): " app_port
    app_port=${app_port:-$current_port}

    read -rp "请输入直连域名 [DIRECT_DOMAIN] (可选，回车留空): " direct_domain
    read -rp "请输入套CDN域名 [GATEWAY_DOMAIN] (可选，回车留空): " gateway_domain
    read -rp "请输入节点名称前缀 [NAME] (可选，回车留空): " node_name
    read -rp "请输入订阅路径 [SUBLINK_PATH] (回车默认: sublink): " sublink_path
    sublink_path=${sublink_path:-sublink}
    read -rp "请输入设置路径 [SETTINGS_PATH] (回车默认: settings): " settings_path
    settings_path=${settings_path:-settings}

    # 写入 Systemd 服务
    echo -e "${YELLOW}>>> 正在配置 Systemd 服务守护 (${SERVICE_FILE})...${PLAIN}"
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Magic Toys Proxy Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
Environment="PORT=${app_port}"
Environment="APP_KEY=${app_key}"
Environment="DIRECT_DOMAIN=${direct_domain}"
Environment="GATEWAY_DOMAIN=${gateway_domain}"
Environment="NAME=${node_name}"
Environment="SUBLINK_PATH=${sublink_path}"
Environment="SETTINGS_PATH=${settings_path}"
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now magic-toys
    systemctl restart magic-toys

    # 确保 Caddy 的内部转发端口与代理服务端口一致
    if [ "$app_port" != "$current_port" ] && [ -f "$CADDY_FILE" ]; then
        sed -i -E "s/reverse_proxy 127.0.0.1:[0-9]+/reverse_proxy 127.0.0.1:${app_port}/g" "$CADDY_FILE"
        reload_caddy
    fi

    echo -e "\n${GREEN}✔ Magic Toys 代理服务已成功安装并启动！${PLAIN}"
    echo -e "----------------------------------------------------"
    echo -e " 🚀 订阅链接: ${CYAN}http(s)://<域名或IP>:${app_port}/${sublink_path}${PLAIN}"
    echo -e " 🛠️ 设置后台: ${CYAN}http(s)://<域名或IP>:${app_port}/${settings_path}${PLAIN}"
    echo -e "----------------------------------------------------"
    read -rp "按回车键继续..."
}

# 3.2 卸载代理服务
uninstall_proxy_app() {
    clear
    echo -e "${RED}====================================================${PLAIN}"
    echo -e "${RED}    卸载 Magic Toys 代理服务                         ${PLAIN}"
    echo -e "${RED}====================================================${PLAIN}"

    read -rp "确认要停止并卸载 Magic Toys 代理服务吗？(y/n): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo -e "${YELLOW}操作已取消。${PLAIN}"
        sleep 1
        return
    fi

    echo -e "${YELLOW}>>> 正在停止并移除服务...${PLAIN}"
    systemctl stop magic-toys 2>/dev/null || true
    systemctl disable magic-toys 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload

    read -rp "是否同时删除项目代码目录 (${APP_DIR})？(y/n): " del_dir
    if [ "$del_dir" = "y" ] || [ "$del_dir" = "Y" ]; then
        rm -rf "$APP_DIR"
        echo -e "${GREEN}✔ 项目代码目录已删除${PLAIN}"
    fi

    echo -e "${GREEN}✔ Magic Toys 代理服务已彻底卸载！${PLAIN}"
    read -rp "按回车键继续..."
}

# ==============================================================================
# 模块 4：卸载脚本与环境清理 (1.完全卸载，2.保留域名证书卸载)
# ==============================================================================
uninstall_all_wizard() {
    while true; do
        clear
        echo -e "${RED}====================================================${PLAIN}"
        echo -e "${RED}    4. 卸载向导与环境清理                            ${PLAIN}"
        echo -e "${RED}====================================================${PLAIN}"
        echo -e " 1. ${RED}完全卸载${PLAIN} (彻底清理 Caddy、代理服务、域名证书与快捷命令)"
        echo -e " 2. ${YELLOW}保留域名证书卸载${PLAIN} (卸载服务并清理命令，保留已申请证书及配置)"
        echo -e " 0. 返回主菜单"
        echo -e "===================================================="
        read -rp "请输入选项 [0-2]: " un_choice

        case "$un_choice" in
            1)
                do_full_uninstall
                ;;
            2)
                do_uninstall_keep_certs
                ;;
            0)
                break
                ;;
            *)
                echo -e "${RED}输入无效，请重新输入！${PLAIN}"
                sleep 1
                ;;
        esac
    done
}

# 4.1 完全卸载
do_full_uninstall() {
    clear
    echo -e "${RED}====================================================${PLAIN}"
    echo -e "${RED}    【完全卸载警告】                                  ${PLAIN}"
    echo -e "${RED}====================================================${PLAIN}"
    echo -e "${YELLOW}此操作将执行：${PLAIN}"
    echo -e " 1. 停止并删除 Magic Toys 代理服务与代码目录"
    echo -e " 2. 停止并彻底卸载 Caddy 反向代理服务"
    echo -e " 3. 删除 Caddyfile 配置文件及所有已申请的域名证书文件"
    echo -e " 4. 删除全局快捷命令 /usr/local/bin/toy"
    echo -e "----------------------------------------------------"
    read -rp "确认要彻底执行【完全卸载】吗？(输入 yes 确认): " confirm
    if [ "$confirm" != "yes" ]; then
        echo -e "${YELLOW}操作已取消。${PLAIN}"
        sleep 1
        return
    fi

    echo -e "${YELLOW}>>> 正在停止并卸载代理服务...${PLAIN}"
    systemctl stop magic-toys 2>/dev/null || true
    systemctl disable magic-toys 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    rm -rf "$APP_DIR"

    echo -e "${YELLOW}>>> 正在停止并卸载 Caddy 服务...${PLAIN}"
    systemctl stop caddy 2>/dev/null || true
    systemctl disable caddy 2>/dev/null || true
    if command -v apt &> /dev/null; then
        apt purge -y caddy 2>/dev/null || true
    elif command -v dnf &> /dev/null; then
        dnf remove -y caddy 2>/dev/null || true
    fi
    rm -f /usr/bin/caddy /usr/local/bin/caddy

    echo -e "${YELLOW}>>> 正在清理配置文件与证书数据...${PLAIN}"
    rm -rf "$CONF_DIR" "/var/lib/caddy" "/etc/systemd/system/caddy.service.d"

    echo -e "${YELLOW}>>> 正在移除全局 toy 快捷命令...${PLAIN}"
    rm -f /usr/local/bin/toy

    systemctl daemon-reload
    echo -e "\n${GREEN}✔ Magic Toys 与 Caddy 全套环境已完全卸载并清理完毕！${PLAIN}"
    exit 0
}

# 4.2 保留域名证书卸载
do_uninstall_keep_certs() {
    clear
    echo -e "${YELLOW}====================================================${PLAIN}"
    echo -e "${YELLOW}    【保留域名证书卸载】                             ${PLAIN}"
    echo -e "${YELLOW}====================================================${PLAIN}"
    echo -e "${CYAN}此操作将执行：${PLAIN}"
    echo -e " 1. 停止并删除 Magic Toys 代理服务与代码目录"
    echo -e " 2. 停止并卸载 Caddy 软件包"
    echo -e " 3. ${GREEN}备份并保留所有已申请的域名证书与 Caddyfile${PLAIN}（备份至 /root/caddy_certs_backup）"
    echo -e " 4. 删除全局快捷命令 /usr/local/bin/toy"
    echo -e "----------------------------------------------------"
    read -rp "确认要执行【保留域名证书卸载】吗？(y/n): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo -e "${YELLOW}操作已取消。${PLAIN}"
        sleep 1
        return
    fi

    echo -e "${YELLOW}>>> 正在备份域名证书与 Caddyfile 到 /root/caddy_certs_backup...${PLAIN}"
    mkdir -p /root/caddy_certs_backup
    [ -d "$CERT_DIR" ] && cp -rf "$CERT_DIR" /root/caddy_certs_backup/ || true
    [ -f "$CADDY_FILE" ] && cp -f "$CADDY_FILE" /root/caddy_certs_backup/ || true

    echo -e "${YELLOW}>>> 正在停止并卸载代理服务...${PLAIN}"
    systemctl stop magic-toys 2>/dev/null || true
    systemctl disable magic-toys 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    rm -rf "$APP_DIR"

    echo -e "${YELLOW}>>> 正在停止并卸载 Caddy 软件包...${PLAIN}"
    systemctl stop caddy 2>/dev/null || true
    systemctl disable caddy 2>/dev/null || true
    if command -v apt &> /dev/null; then
        apt remove -y caddy 2>/dev/null || true
    elif command -v dnf &> /dev/null; then
        dnf remove -y caddy 2>/dev/null || true
    fi
    rm -f /usr/bin/caddy /usr/local/bin/caddy
    rm -f /usr/local/bin/toy

    systemctl daemon-reload
    echo -e "\n${GREEN}✔ 服务已成功卸载！${PLAIN}"
    echo -e "${GREEN}✔ 域名证书与配置已安全保留在：${CYAN}/root/caddy_certs_backup${PLAIN} 与 ${CYAN}${CONF_DIR}${PLAIN}"
    exit 0
}

# ==============================================================================
# 模块 5：查看系统运行状态与实时日志
# ==============================================================================
view_caddy_status_logs() {
    clear
    echo -e "${CYAN}====================================================${PLAIN}"
    echo -e "${CYAN}    5. 系统运行状态与实时日志                       ${PLAIN}"
    echo -e "${CYAN}====================================================${PLAIN}"
    echo -e "${GREEN}【Caddy 服务状态】：${PLAIN}"
    systemctl status caddy --no-pager || true
    echo -e "\n${GREEN}【Magic Toys 代理服务状态】：${PLAIN}"
    systemctl status magic-toys --no-pager 2>/dev/null || echo -e "${YELLOW}未安装或未运行${PLAIN}"
    echo -e "\n${YELLOW}>>> Caddy 最近 15 条实时日志：${PLAIN}"
    journalctl -u caddy -n 15 --no-pager || true
    echo -e "\n${YELLOW}>>> Magic Toys 最近 15 条实时日志：${PLAIN}"
    journalctl -u magic-toys -n 15 --no-pager 2>/dev/null || true
    echo -e "----------------------------------------------------"
    read -rp "按回车键返回主菜单..."
}

# ==============================================================================
# 模块 6：服务启停控制
# ==============================================================================
manage_caddy_service() {
    clear
    echo -e "${CYAN}====================================================${PLAIN}"
    echo -e "${CYAN}    6. 服务启停运维控制                             ${PLAIN}"
    echo -e "${CYAN}====================================================${PLAIN}"
    echo -e " 1. 启动所有服务 (Caddy & 代理服务)"
    echo -e " 2. 停止所有服务 (Caddy & 代理服务)"
    echo -e " 3. 重启所有服务 (Caddy & 代理服务)"
    echo -e " 4. 仅重启 Caddy 服务"
    echo -e " 5. 仅重启 Magic Toys 代理服务"
    echo -e " 0. 返回主菜单"
    echo -e "----------------------------------------------------"
    read -rp "请选择操作 [0-5]: " svc_choice
    case "$svc_choice" in
        1)
            systemctl start caddy 2>/dev/null || true
            systemctl start magic-toys 2>/dev/null || true
            echo -e "${GREEN}✔ 服务已全部启动${PLAIN}"
            ;;
        2)
            systemctl stop caddy 2>/dev/null || true
            systemctl stop magic-toys 2>/dev/null || true
            echo -e "${YELLOW}✔ 服务已全部停止${PLAIN}"
            ;;
        3)
            systemctl restart caddy 2>/dev/null || true
            systemctl restart magic-toys 2>/dev/null || true
            echo -e "${GREEN}✔ 服务已全部重启${PLAIN}"
            ;;
        4)
            systemctl restart caddy && echo -e "${GREEN}✔ Caddy 已重启${PLAIN}"
            ;;
        5)
            systemctl restart magic-toys && echo -e "${GREEN}✔ Magic Toys 代理服务已重启${PLAIN}"
            ;;
        0) return ;;
        *) echo -e "${RED}无效输入！${PLAIN}" ;;
    esac
    sleep 1
}

# ==============================================================================
# 主菜单循环
# ==============================================================================
main_menu() {
    check_root
    install_toy_alias
    ensure_caddy_installed

    while true; do
        clear
        echo -e "${CYAN}====================================================${PLAIN}"
        echo -e "${GREEN}        Magic Toys · 一键管理向导                   ${PLAIN}"
        echo -e "${YELLOW}       (随时输入 ${GREEN}toy${YELLOW} 即可再次唤醒本向导)          ${PLAIN}"
        echo -e "${CYAN}====================================================${PLAIN}"
        local current_listen=$(get_listen_ports_summary)
        local current_backend=$(get_backend_port)
        echo -e "Caddy当前监听端口: ${GREEN}${current_listen}${PLAIN}"
        echo -e "当前内部转发端口: ${GREEN}${current_backend}${PLAIN} (h2c 转发至 127.0.0.1:${current_backend})"
        echo -e "当前已配域名数量: ${GREEN}$(get_configured_domains | wc -w)${PLAIN}"
        echo -e "代理服务运行状态: $(get_app_service_status)"
        echo -e "----------------------------------------------------"
        echo -e " ${GREEN}1.${PLAIN} Caddy 端口配置与流量转发 (对内/对外)"
        echo -e " ${GREEN}2.${PLAIN} 证书与域名管理 (CF Token / HTTP / 自签 / 删除)"
        echo -e " ${GREEN}3.${PLAIN} 代理脚本配置 ${CYAN}(1.安装，2.卸载)${PLAIN}"
        echo -e " ${GREEN}4.${PLAIN} 卸载向导与环境清理 ${RED}(1.完全卸载，2.保留域名证书卸载)${PLAIN}"
        echo -e " ${GREEN}5.${PLAIN} 查看系统运行状态与实时日志 (Caddy & 代理服务)"
        echo -e " ${GREEN}6.${PLAIN} 启动 / 停止 / 重启服务"
        echo -e " ${RED}0.${PLAIN} 退出向导"
        echo -e "===================================================="
        read -rp "请输入操作编号 [0-6]: " choice

        case "$choice" in
            1)
                configure_ports_and_proxy
                ;;
            2)
                manage_certificates
                ;;
            3)
                manage_proxy_app
                ;;
            4)
                uninstall_all_wizard
                ;;
            5)
                view_caddy_status_logs
                ;;
            6)
                manage_caddy_service
                ;;
            0)
                echo -e "${GREEN}感谢使用 Magic Toys！在终端输入 ${YELLOW}toy${GREEN} 即可随时再次打开本向导。${PLAIN}"
                exit 0
                ;;
            *)
                echo -e "${RED}输入有误，请输入 0-6 之间的数字！${PLAIN}"
                sleep 1
                ;;
        esac
    done
}

main_menu
