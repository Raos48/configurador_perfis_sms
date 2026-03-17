"""
Módulo de coleta de métricas de execução do RPA.
Mantém contadores de operações bem-sucedidas, falhas e tempos de execução.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger("RPA.Metrics")

@dataclass
class OperationStats:
    count: int = 0
    success: int = 0
    failure: int = 0
    total_time: float = 0.0
    
    @property
    def avg_time(self) -> float:
        return self.total_time / self.count if self.count > 0 else 0.0


class MetricsCollector:
    """
    Coletor de métricas simples em memória.
    Singleton para ser acessado de qualquer lugar do serviço.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MetricsCollector, cls).__new__(cls)
            cls._instance._reset()
        return cls._instance

    def _reset(self):
        self.stats: Dict[str, OperationStats] = {}
        self.start_time = time.time()

    def record_operation(self, operation_type: str, success: bool, duration: float):
        """
        Registra uma operação.
        
        Args:
            operation_type: Tipo da operação (ex: "BLOQUEIO", "DESBLOQUEIO")
            success: True se bem-sucedido
            duration: Duração em segundos
        """
        if operation_type not in self.stats:
            self.stats[operation_type] = OperationStats()
            
        stat = self.stats[operation_type]
        stat.count += 1
        stat.total_time += duration
        
        if success:
            stat.success += 1
        else:
            stat.failure += 1

    def log_summary(self):
        """Loga um resumo das métricas acumuladas."""
        uptime = time.time() - self.start_time
        logger.info("=== RESUMO DE MÉTRICAS ===")
        logger.info(f"Uptime: {uptime:.1f}s")
        
        total_ops = sum(s.count for s in self.stats.values())
        if total_ops == 0:
            logger.info("Nenhuma operação registrada ainda.")
            return

        for op_type, stat in self.stats.items():
            logger.info(
                f"[{op_type}] Total: {stat.count} | "
                f"Sucesso: {stat.success} | "
                f"Falha: {stat.failure} | "
                f"Tempo Médio: {stat.avg_time:.2f}s"
            )
        logger.info("==========================")
