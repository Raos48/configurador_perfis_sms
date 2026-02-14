"""
Script de teste para visualizar os logs coloridos.
Executa alguns logs de exemplo para demonstrar as cores.
"""

import logging
from colored_logger import setup_colored_logging, print_startup_banner, print_shutdown_banner

# Configurar logging com cores
setup_colored_logging(log_level=logging.DEBUG)
logger = logging.getLogger("TesteColorido")

def main():
    # Banner de início
    print_startup_banner("http://localhost:8000", 30, 60)

    # Testes de diferentes níveis de log
    logger.debug("Mensagem de DEBUG - informações detalhadas do sistema")
    logger.info("Mensagem de INFO - operação normal")
    logger.warning("Mensagem de WARNING - atenção necessária")
    logger.error("Mensagem de ERROR - algo deu errado")
    logger.critical("Mensagem de CRITICAL - falha grave do sistema")

    print()

    # Testes com palavras-chave destacadas
    logger.info("Autenticação inicial com a API SIGA: OK")
    logger.info("Encontrados 3 bloqueio(s) pendente(s).")
    logger.info("[BLOQUEIO #1893] Iniciando: SIAPE=1960398, Unidade=23150521")
    logger.info("[BLOQUEIO #1893] SUCESSO - Confirmado na API.")
    logger.warning("[BLOQUEIO #1894] FALHA - Servidor não encontrado - Reportado à API.")

    print()

    logger.info("[DESBLOQUEIO #2001] Iniciando: SIAPE=2035843, Unidade=085211")
    logger.info("[DESBLOQUEIO #2001] SUCESSO - Confirmado na API.")
    logger.error("[BLOQUEIO #1895] ERRO ao confirmar na API: HTTP 500")

    print()

    logger.info("=" * 60)
    logger.info("Ciclo concluído: 5 item(ns) processado(s).")
    logger.info("=" * 60)

    print()

    # Banner de encerramento
    print_shutdown_banner()

if __name__ == "__main__":
    main()
