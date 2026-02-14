"""
Serviço RPA de Bloqueio de Perfis - Loop Principal de Polling.

Este script é o ponto de entrada do serviço. Ele:
1. Conecta-se à API do Sistema SIGA via JWT
2. Busca pedidos pendentes de bloqueio e desbloqueio
3. Executa cada pedido no SAGGESTAO via browser automation
4. Confirma o resultado de volta à API
5. Aguarda e repete

Uso:
    python servico_rpa.py

Para encerrar: Ctrl+C
"""

import time
import logging
import sys

from config import (
    SIGA_API_URL,
    SIGA_EMAIL,
    SIGA_PASSWORD,
    POLLING_INTERVAL,
    POLLING_INTERVAL_IDLE,
    LOG_FILE,
    LOG_LEVEL,
)
from siga_client import SigaApiClient
from bloquear_perfis import executar_bloqueio
from session_manager import SaggestaoSessionManager
from colored_logger import setup_colored_logging, print_startup_banner, print_shutdown_banner, print_heartbeat

# ============================================
# Configuração de Logging com Cores
# ============================================
log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
setup_colored_logging(log_level=log_level, log_file=LOG_FILE)
logger = logging.getLogger("RPA.Servico")


def processar_pendentes_bloqueio(cliente: SigaApiClient, session_manager: SaggestaoSessionManager) -> int:
    """
    Busca e processa todos os bloqueios pendentes.

    Returns:
        Quantidade de itens processados.
    """
    try:
        pendentes = cliente.buscar_pendentes_bloqueio()
    except Exception as e:
        logger.error(f"Erro ao buscar pendentes de bloqueio: {e}")
        return 0

    if not pendentes:
        return 0

    logger.info(f"Encontrados {len(pendentes)} bloqueio(s) pendente(s).")
    processados = 0

    for item in pendentes:
        bloqueio_id = item['id']
        siape = item['servidor']['siape']
        codigo_unidade = item['codigo_unidade']

        logger.info(f"[BLOQUEIO #{bloqueio_id}] Iniciando: SIAPE={siape}, Unidade={codigo_unidade}")

        try:
            sucesso, erro = executar_bloqueio(siape, codigo_unidade, "BLOQUEIO", session_manager)

            # Confirmar resultado na API
            try:
                resposta = cliente.confirmar_bloqueio(bloqueio_id, sucesso, erro or "")
                if sucesso:
                    logger.info(f"[BLOQUEIO #{bloqueio_id}] SUCESSO - Confirmado na API.")
                else:
                    logger.warning(f"[BLOQUEIO #{bloqueio_id}] FALHA - {erro} - Reportado à API.")
            except Exception as e:
                logger.error(f"[BLOQUEIO #{bloqueio_id}] Erro ao confirmar na API: {e}")

        except Exception as e:
            # Erro inesperado na automação - tenta reportar à API
            msg = f"Erro inesperado na automação: {str(e)}"
            logger.error(f"[BLOQUEIO #{bloqueio_id}] {msg}")
            try:
                cliente.confirmar_bloqueio(bloqueio_id, False, msg[:500])
            except Exception:
                logger.error(f"[BLOQUEIO #{bloqueio_id}] Falha ao reportar erro à API.")

        processados += 1

    return processados


def processar_pendentes_desbloqueio(cliente: SigaApiClient, session_manager: SaggestaoSessionManager) -> int:
    """
    Busca e processa todos os desbloqueios pendentes.

    Returns:
        Quantidade de itens processados.
    """
    try:
        pendentes = cliente.buscar_pendentes_desbloqueio()
    except Exception as e:
        logger.error(f"Erro ao buscar pendentes de desbloqueio: {e}")
        return 0

    if not pendentes:
        return 0

    logger.info(f"Encontrados {len(pendentes)} desbloqueio(s) pendente(s).")
    processados = 0

    for item in pendentes:
        bloqueio_id = item['id']
        siape = item['servidor']['siape']
        codigo_unidade = item['codigo_unidade']

        logger.info(f"[DESBLOQUEIO #{bloqueio_id}] Iniciando: SIAPE={siape}, Unidade={codigo_unidade}")

        try:
            sucesso, erro = executar_bloqueio(siape, codigo_unidade, "DESBLOQUEIO", session_manager)

            # Confirmar resultado na API
            try:
                resposta = cliente.confirmar_desbloqueio(bloqueio_id, sucesso, erro or "")
                if sucesso:
                    logger.info(f"[DESBLOQUEIO #{bloqueio_id}] SUCESSO - Confirmado na API.")
                else:
                    logger.warning(f"[DESBLOQUEIO #{bloqueio_id}] FALHA - {erro} - Reportado à API.")
            except Exception as e:
                logger.error(f"[DESBLOQUEIO #{bloqueio_id}] Erro ao confirmar na API: {e}")

        except Exception as e:
            msg = f"Erro inesperado na automação: {str(e)}"
            logger.error(f"[DESBLOQUEIO #{bloqueio_id}] {msg}")
            try:
                cliente.confirmar_desbloqueio(bloqueio_id, False, msg[:500])
            except Exception:
                logger.error(f"[DESBLOQUEIO #{bloqueio_id}] Falha ao reportar erro à API.")

        processados += 1

    return processados


def main():
    """Loop principal do serviço RPA de bloqueio de perfis."""
    print_startup_banner(SIGA_API_URL, POLLING_INTERVAL, POLLING_INTERVAL_IDLE)

    # Inicializar cliente da API
    cliente = SigaApiClient(SIGA_API_URL, SIGA_EMAIL, SIGA_PASSWORD)

    # Testar autenticação antes de entrar no loop
    try:
        cliente._autenticar()
        logger.info("Autenticação inicial com a API SIGA: OK")
    except Exception as e:
        logger.critical(f"Falha na autenticação inicial: {e}")
        logger.critical("Verifique as credenciais em config.py e se a API está rodando.")
        sys.exit(1)

    # Inicializar gerenciador de sessão do browser (lazy start)
    session_manager = SaggestaoSessionManager()

    # Loop principal de polling
    try:
        while True:
            try:
                total_processados = 0

                # 1. Processar bloqueios pendentes
                total_processados += processar_pendentes_bloqueio(cliente, session_manager)

                # 2. Processar desbloqueios pendentes
                total_processados += processar_pendentes_desbloqueio(cliente, session_manager)

                # 3. Keep-alive em ciclos ociosos (apenas se sessão já foi iniciada)
                if total_processados == 0 and session_manager._active:
                    try:
                        session_manager.ensure_ready()
                    except Exception as e:
                        logger.warning(f"Erro durante keep-alive: {e}")

                # 4. Sinal de vida - mostra resumo do ciclo com data/hora
                print_heartbeat(total_processados)

                # 5. Aguardar próximo ciclo
                intervalo = POLLING_INTERVAL if total_processados > 0 else POLLING_INTERVAL_IDLE
                time.sleep(intervalo)

            except KeyboardInterrupt:
                raise

            except Exception as e:
                logger.error(f"Erro inesperado no ciclo de polling: {e}", exc_info=True)
                logger.info(f"Aguardando {POLLING_INTERVAL}s antes de tentar novamente...")
                time.sleep(POLLING_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        print_shutdown_banner()
        session_manager.shutdown()


if __name__ == "__main__":
    main()
