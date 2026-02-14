"""
Cliente HTTP para comunicação com a API do Sistema SIGA.
Gerencia autenticação JWT com refresh automático de tokens.
"""

import time
import logging
import requests

# Logger será configurado pelo módulo principal (servico_rpa.py)
logger = logging.getLogger("RPA.SigaClient")


class SigaApiClient:
    """
    Cliente para a API REST do Sistema SIGA.

    Gerencia autenticação JWT, refresh automático de tokens,
    e expõe métodos para os endpoints usados pelo RPA.
    """

    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.access_token = None
        self.refresh_token = None
        self.token_obtido_em = 0  # timestamp de quando o access token foi obtido

    # ============================================
    # Autenticação JWT
    # ============================================

    def _autenticar(self):
        """
        Obtém novos tokens JWT via POST /api/token/.
        Levanta exceção se falhar.
        """
        url = f"{self.base_url}/api/token/"
        logger.info("Autenticando na API SIGA...")

        try:
            response = requests.post(url, json={
                "email": self.email,
                "password": self.password
            }, timeout=15)

            if response.status_code == 200:
                data = response.json()
                self.access_token = data["access"]
                self.refresh_token = data["refresh"]
                self.token_obtido_em = time.time()
                logger.info("Autenticação realizada com sucesso.")
            else:
                erro = response.text[:200]
                logger.error(f"Falha na autenticação: HTTP {response.status_code} - {erro}")
                raise Exception(f"Falha na autenticação: HTTP {response.status_code}")

        except requests.exceptions.ConnectionError:
            logger.error(f"Não foi possível conectar à API SIGA em {self.base_url}")
            raise
        except requests.exceptions.Timeout:
            logger.error("Timeout ao tentar autenticar na API SIGA")
            raise

    def _refresh_token_jwt(self):
        """
        Renova o access token via POST /api/token/refresh/.
        Retorna True se bem-sucedido, False se falhar.
        """
        if not self.refresh_token:
            return False

        url = f"{self.base_url}/api/token/refresh/"
        logger.debug("Renovando access token...")

        try:
            response = requests.post(url, json={
                "refresh": self.refresh_token
            }, timeout=15)

            if response.status_code == 200:
                data = response.json()
                self.access_token = data["access"]
                # Se a API rotaciona refresh tokens, atualiza o refresh também
                if "refresh" in data:
                    self.refresh_token = data["refresh"]
                self.token_obtido_em = time.time()
                logger.debug("Access token renovado com sucesso.")
                return True
            else:
                logger.warning(f"Falha ao renovar token: HTTP {response.status_code}")
                return False

        except Exception as e:
            logger.warning(f"Erro ao renovar token: {e}")
            return False

    def _garantir_token_valido(self):
        """
        Garante que temos um access token válido.
        Faz refresh proativo se o token tem mais de 12 minutos (validade: 15 min).
        """
        if not self.access_token:
            self._autenticar()
            return

        # Refresh proativo: se o token tem mais de 12 minutos, renova
        tempo_desde_obtencao = time.time() - self.token_obtido_em
        if tempo_desde_obtencao > 720:  # 12 minutos
            logger.debug("Token próximo de expirar, renovando proativamente...")
            if not self._refresh_token_jwt():
                logger.info("Refresh falhou, fazendo autenticação completa...")
                self._autenticar()

    # ============================================
    # Request genérico com retry de auth
    # ============================================

    def _request(self, method: str, endpoint: str, data: dict = None) -> dict | list:
        """
        Executa uma request HTTP com autenticação JWT.

        Se receber 401, tenta refresh do token e re-envia.
        Se refresh falhar, faz autenticação completa e re-envia.

        Args:
            method: "GET" ou "POST"
            endpoint: Caminho relativo (ex: "/api/bloqueios/pendentes-bloqueio/")
            data: Dados para POST (opcional)

        Returns:
            Resposta JSON parseada (dict ou list)

        Raises:
            Exception: Se a request falhar após tentativas de re-auth
        """
        self._garantir_token_valido()

        url = f"{self.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        for tentativa in range(2):
            try:
                if method.upper() == "GET":
                    response = requests.get(url, headers=headers, timeout=30)
                elif method.upper() == "POST":
                    response = requests.post(url, json=data, headers=headers, timeout=30)
                else:
                    raise ValueError(f"Método HTTP não suportado: {method}")

                # Sucesso
                if response.status_code in (200, 201, 202):
                    return response.json()

                # Token expirado - tenta renovar
                if response.status_code == 401 and tentativa == 0:
                    logger.info("Token expirado (401). Tentando renovar...")
                    if not self._refresh_token_jwt():
                        logger.info("Refresh falhou. Re-autenticando...")
                        self._autenticar()
                    headers = {"Authorization": f"Bearer {self.access_token}"}
                    continue

                # Outros erros
                erro = response.text[:300]
                logger.error(f"Erro na API: {method} {endpoint} → HTTP {response.status_code}: {erro}")
                raise Exception(f"API retornou HTTP {response.status_code}: {erro}")

            except requests.exceptions.ConnectionError:
                logger.error(f"Sem conexão com a API SIGA ({url})")
                raise
            except requests.exceptions.Timeout:
                logger.error(f"Timeout na request: {method} {url}")
                raise

        raise Exception(f"Falha após tentativas de re-autenticação: {method} {endpoint}")

    # ============================================
    # Endpoints de Polling (buscar pendentes)
    # ============================================

    def buscar_pendentes_bloqueio(self) -> list:
        """
        Busca bloqueios com status BLOQUEIO_PROCESSAMENTO.

        GET /api/bloqueios/pendentes-bloqueio/

        Returns:
            Lista de dicts com dados dos bloqueios pendentes.
            Cada item contém: id, servidor (com siape), codigo_unidade, etc.
        """
        return self._request("GET", "/api/bloqueios/pendentes-bloqueio/")

    def buscar_pendentes_desbloqueio(self) -> list:
        """
        Busca bloqueios com status DESBLOQUEIO_PROCESSAMENTO.

        GET /api/bloqueios/pendentes-desbloqueio/

        Returns:
            Lista de dicts com dados dos desbloqueios pendentes.
        """
        return self._request("GET", "/api/bloqueios/pendentes-desbloqueio/")

    # ============================================
    # Endpoints de Confirmação (devolver resultado)
    # ============================================

    def confirmar_bloqueio(self, bloqueio_id: int, sucesso: bool, erro: str = "") -> dict:
        """
        Confirma resultado da execução de um bloqueio no SAGGESTAO.

        POST /api/bloqueios/confirmar-bloqueio/

        Args:
            bloqueio_id: ID do registro de bloqueio na API SIGA
            sucesso: True se bloqueio foi executado com sucesso
            erro: Mensagem de erro (quando sucesso=False)

        Returns:
            Resposta da API: {"sucesso": bool, "mensagem": str}
        """
        return self._request("POST", "/api/bloqueios/confirmar-bloqueio/", {
            "bloqueio_id": bloqueio_id,
            "sucesso": sucesso,
            "erro": erro
        })

    def confirmar_desbloqueio(self, bloqueio_id: int, sucesso: bool, erro: str = "") -> dict:
        """
        Confirma resultado da execução de um desbloqueio no SAGGESTAO.

        POST /api/bloqueios/confirmar-desbloqueio/

        Args:
            bloqueio_id: ID do registro de bloqueio na API SIGA
            sucesso: True se desbloqueio foi executado com sucesso
            erro: Mensagem de erro (quando sucesso=False)

        Returns:
            Resposta da API: {"sucesso": bool, "mensagem": str}
        """
        return self._request("POST", "/api/bloqueios/confirmar-desbloqueio/", {
            "bloqueio_id": bloqueio_id,
            "sucesso": sucesso,
            "erro": erro
        })
