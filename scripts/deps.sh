#!/bin/bash
# scripts/deps.sh — централизованная библиотека зависимостей ZapretPass
# Используется install.sh и uninstall.sh для маппинга пакетов по дистрибутивам

# Возвращает имя пакета для конкретного пакетного менеджера
# Аргументы: $1=canonical_name, $2=pkg_manager
get_package_name() {
    local canonical="$1"
    local pkg_manager="$2"
    
    case "$canonical" in
        build_tools)
            case "$pkg_manager" in
                pacman) echo "base-devel" ;;
                apt)    echo "build-essential" ;;
                dnf)    echo "development-tools" ;;
                apk)    echo "build-base" ;;
                *)      echo "base-devel" ;;
            esac
            ;;
        
        libcap)
            case "$pkg_manager" in
                pacman) echo "libcap" ;;
                apt)    echo "libcap2" ;;
                dnf)    echo "libcap" ;;
                apk)    echo "libcap" ;;
                *)      echo "libcap" ;;
            esac
            ;;
        
        libcap_dev)
            case "$pkg_manager" in
                pacman) echo "libcap" ;;
                apt)    echo "libcap-dev" ;;
                dnf)    echo "libcap-devel" ;;
                apk)    echo "libcap-dev" ;;
                *)      echo "libcap-dev" ;;
            esac
            ;;
        
        dns_utils)
            case "$pkg_manager" in
                pacman) echo "bind-tools" ;;
                apt)    echo "bind9-dnsutils" ;;
                dnf)    echo "bind-utils" ;;
                apk)    echo "bind-tools" ;;
                *)      echo "bind-tools" ;;
            esac
            ;;
        
        python)
            case "$pkg_manager" in
                pacman) echo "python" ;;
                apt)    echo "python3" ;;
                dnf)    echo "python3" ;;
                apk)    echo "python3" ;;
                *)      echo "python3" ;;
            esac
            ;;
        
        pyqt6)
            case "$pkg_manager" in
                pacman) echo "python-pyqt6" ;;
                apt)    echo "python3-pyqt6" ;;
                dnf)    echo "python3-qt6" ;;
                apk)    echo "py3-qt6" ;;
                *)      echo "python3-pyqt6" ;;
            esac
            ;;
        
        pyqt6_webengine)
            case "$pkg_manager" in
                pacman) echo "python-pyqt6-webengine" ;;
                apt)    echo "python3-pyqt6.qtwebengine" ;;
                dnf)    echo "python3-qt6-webengine" ;;
                apk)    echo "py3-qt6-webengine" ;;
                *)      echo "python3-pyqt6-webengine" ;;
            esac
            ;;
        
        libnetfilter_queue)
            case "$pkg_manager" in
                pacman) echo "libnetfilter_queue" ;;
                apt)    echo "libnetfilter-queue1" ;;
                dnf)    echo "libnetfilter_queue" ;;
                apk)    echo "libnetfilter_queue" ;;
                *)      echo "libnetfilter_queue" ;;
            esac
            ;;
        
        libmnl)
            case "$pkg_manager" in
                pacman) echo "libmnl" ;;
                apt)    echo "libmnl0" ;;
                dnf)    echo "libmnl" ;;
                apk)    echo "libmnl" ;;
                *)      echo "libmnl" ;;
            esac
            ;;
        
        dnscrypt_proxy)
            case "$pkg_manager" in
                pacman) echo "dnscrypt-proxy" ;;
                apt)    echo "dnscrypt-proxy" ;;
                dnf)    echo "dnscrypt-proxy" ;;
                apk)    echo "dnscrypt-proxy" ;;
                *)      echo "dnscrypt-proxy" ;;
            esac
            ;;
        
        *)
            # Fallback: возвращаем каноническое имя
            echo "$canonical"
            ;;
    esac
}

# Списки необходимых пакетов (канонические имена)
PACKAGES_CORE=(build_tools git curl make gcc libcap libnetfilter_queue libmnl dns_utils iproute2)
PACKAGES_UI=(python pyqt6 pyqt6_webengine)
PACKAGES_DOT=(dnscrypt_proxy)
