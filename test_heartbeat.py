"""
Script de demonstração do sinal de vida (heartbeat) do serviço.
Simula ciclos de polling mostrando o timestamp e status.
"""

import time
from colored_logger import print_startup_banner, print_heartbeat, print_shutdown_banner

def main():
    # Banner de início
    print_startup_banner("http://localhost:8000", 5, 10)

    print("Simulando 10 ciclos de polling (5 segundos cada)...\n")

    try:
        for i in range(10):
            # Simula processamento variado
            if i % 3 == 0:
                # Ciclo com processamento
                total = (i % 4) + 1
                print_heartbeat(total)
            else:
                # Ciclo sem processamento
                print_heartbeat(0)

            time.sleep(5)

    except KeyboardInterrupt:
        pass

    print_shutdown_banner()

if __name__ == "__main__":
    main()
