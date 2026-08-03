"""Печатает адрес, по которому приложение открывается с телефона.

Нужен потому, что `ipconfig` показывает несколько адресов — реальный сетевой,
виртуальные адаптеры Docker и WSL, — и угадать нужный непросто.

Здесь берётся тот адрес, через который компьютер реально ходит в сеть:
открывается служебный UDP-сокет к внешнему адресу (пакеты при этом не шлются)
и спрашивается, какой интерфейс для этого выбрала система.

Запуск:  python tools/show_url.py
"""
import socket

PORT = 8000


def local_ip() -> str | None:
    """IP того интерфейса, через который идёт маршрут наружу."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # соединение не устанавливается
        ip = s.getsockname()[0]
        return ip if not ip.startswith("127.") else None
    except OSError:
        return None
    finally:
        s.close()


def fallback_ips() -> list[str]:
    """Запасной вариант, если маршрут наружу недоступен."""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except OSError:
        pass
    return out


def main() -> None:
    print()
    print("  =================================================")
    print(f"  На этом компьютере:  http://localhost:{PORT}/app")

    ip = local_ip()
    if ip:
        print(f"  С телефона:          http://{ip}:{PORT}/app")
        print()
        print("  Телефон должен быть в той же Wi-Fi сети.")
    else:
        others = fallback_ips()
        if others:
            print("  С телефона — попробуйте один из адресов:")
            for a in others:
                print(f"                       http://{a}:{PORT}/app")
        else:
            print("  Адрес для телефона определить не удалось.")
            print("  Посмотрите вручную: ipconfig -> строка IPv4-адрес")
    print("  =================================================")
    print()


if __name__ == "__main__":
    main()
