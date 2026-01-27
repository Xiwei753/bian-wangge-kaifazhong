#所有可以改动的，可以开关的，比如交易对，网格参数，等等。用btcusdc合约，双向持仓，固定100倍杠杆。每个仓位用20u保证金。固定交易精度和下单精度为0.1（四舍五入。）
#一个不正确但是大概没问题的例子，可能语法有问题，但是其他参数没有问题
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MarketMode(str, Enum):
    CONSOLIDATION = "consolidation"
    TREND = "trend"

@dataclass
class GridConfig:
    """网格策略配置 - 完整动态网格版本"""

    def __init__(self):
        # ===================== 基础交易配置 =====================
        self.symbol: str = "BTCUSDC"
        self.timeframe_minutes: int = 3
        self.initial_capital: float = 10000
        self.leverage: int = 10
        self.margin_mode: str = "CROSSED"
        self.grid_step_ratio: float = 0.002
        self.long_open_short_tp_step_ratio: float = 0.002
        self.short_open_long_tp_step_ratio: float = 0.002
        self.market_mode: MarketMode = MarketMode.CONSOLIDATION

        # ===================== 趋势评分配置 =====================
        self.score_bullish: float = 3.0
        self.score_bearish: float = -3.0

        # ===================== 信号延续配置 =====================
        self.confidence_penalty: float = 0.7
        self.persistence_bonus: float = 1.1

        # ===================== 状态切换阈值配置 =====================
        self.base_activation: float = 0.6
        self.volatility_factor: float = 0.2

        # ===================== 动态权重配置 =====================
        self.weight_bb_default: float = 0.4
        self.weight_atr_default: float = 0.4
        self.weight_trend_default: float = 0.2

        # ===================== 网格调整配置 =====================
        self.trend_compression_max: float = 0.4
        self.counter_expansion_max: float = 1.0
        
        # ===================== 功能开关配置 =====================
        self.enable_wechat_push: bool = True
        self.wechat_webhook_url: str = (
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=43874765-eb79-481d-84ce-3773b1e879d7"
        )
        self.enable_short: bool = True
        self.enable_flexible_tp: bool = True
        self.enable_profit_stop_for_trapped: bool = True

        # ===================== 网格基础参数 =====================
        self.grid_count: int = 3
        self.fixed_order_size: float = 0.01
        self.position_report_interval: int = 180
        
        # ===================== 动态网格管理配置 =====================
        self.consolidation_step_min_ratio: float = 0.0025
        self.consolidation_step_max_ratio: float = 0.006
        self.trend_follow_step_min_ratio: float = 0.001
        self.trend_follow_step_max_ratio: float = 0.003
        self.counter_trend_step_min_ratio: float = 0.004
        self.counter_trend_step_max_ratio: float = 0.01
        self.trend_activation_threshold: float = 0.6
        self.extreme_trend_threshold: float = 0.8
        self.volatility_spike_threshold: float = 2.0
        self.redeploy_price_threshold: float = 0.02
        self.redeploy_step_change_threshold: float = 0.5
        self.trend_change_cooldown: int = 300
        
        # ===================== 动态权重配置 =====================
        self.base_bollinger_weight: float = 0.4
        self.base_atr_weight: float = 0.4
        self.base_trend_weight: float = 0.2
        
        # ===================== 趋势乘数配置 =====================
        self.trend_follow_multiplier_min: float = 0.1
        self.trend_follow_multiplier_max: float = 1.0
        self.counter_trend_multiplier_min: float = 1.0
        self.counter_trend_multiplier_max: float = 3.0
        
        # ===================== 仓位调整配置 =====================
        self.position_adjustment_range: float = 0.03
        self.tp_adjustment_cooldown: int = 60
        
        # ===================== 止盈配置 =====================
        self.trend_follow_tp_base_ratio: float = 0.004
        self.trend_follow_tp_boost_max: float = 0.008
        self.counter_trend_tp_min_ratio: float = 0.001
        self.counter_trend_tp_base_ratio: float = 0.002
        self.consolidation_tp_ratio: float = 0.003
        self.normal_tp_ratio: float = 0.002
        self.min_tp_ratio: float = 0.001
        self.counter_trend_tp_ratio: float = 0.0015
        
        # ===================== 网格间距系数 =====================
        self.trend_follow_spacing_min: float = 0.3
        self.trend_follow_spacing_max: float = 0.8
        self.counter_trend_spacing_min: float = 1.5
        self.counter_trend_spacing_max: float = 3.0
        self.consolidation_spacing: float = 1.0
        
        # ===================== 技术指标参数 =====================
        self.atr_length: int = 14
        self.atr_mult_normal: float = 20.0
        self.atr_mult_attack: float = 6.0
        self.min_grid_step_ratio: float = 0.004
        
        # ===================== 趋势适应参数 =====================
        self.trend_adjustment_factor: float = 0.3
        self.min_trend_strength: int = 20
        self.consolidation_atr_ratio: float = 0.3
        
        # ===================== 网格优化参数 =====================
        self.aggressive_grid_count: int = 5
        self.defensive_grid_count: int = 3
        self.trend_grid_spacing: float = 1.5
        self.counter_trend_grid_spacing: float = 2.5
        
        # ===================== 信号延续参数 =====================
        self.signal_confirmation_periods: int = 2
        self.min_signal_strength: float = 0.6
        
        # ===================== 波动率参数 =====================
        self.volatility_lookback: int = 10
        self.min_volatility_ratio: float = 0.3
        
        # ===================== 趋势过滤参数 =====================
        self.min_trend_strength: float = 0.6
        self.min_trend_confidence: float = 0.6
        self.min_trend_duration: int = 2
        
        # ===================== 套牢仓位参数 =====================
        self.trapped_position_range: float = 0.03
        
        # ===================== 智能响应配置 =====================
        self.max_deploy_frequency_5min: int = 8  # 5分钟内最大部署次数
        self.emergency_volume_multiplier: float = 3.0  # 紧急情况成交量倍数
        self.emergency_price_change: float = 0.02  # 紧急情况价格变动阈值
        
        # ===================== 动态阈值配置 =====================
        self.high_volatility_threshold: float = 0.03  # 高波动率阈值
        self.medium_volatility_threshold: float = 0.015  # 中等波动率阈值
        self.low_volatility_strength_threshold: float = 0.5  # 低波动率趋势强度阈值
        self.medium_volatility_strength_threshold: float = 0.6  # 中等波动率趋势强度阈值
        self.high_volatility_strength_threshold: float = 0.7  # 高波动率趋势强度阈值
        
        # ===================== API配置 =====================
        # Binance Python Connector (USDT-M 合约)
        self.api_key: str = ""
        self.api_secret: str = ""
        self.use_testnet: bool = True
        self.base_url_testnet: str = "https://testnet.binancefuture.com"
        self.base_url_live: str = "https://fapi.binance.com"
        self.recv_window: int = 5000
        self.request_timeout: int = 10
        self.api_key_test: Optional[str] = "GpTMMRi3M92kZGFUErS7UfS2vl0TaBzgNtb1lWIhjIwaIsGcd4PrAcu3eRTsmcdJ"
        self.api_secret_test: Optional[str] = "fpPn45zFzRoBxKBpcJiQjkjkrzhQVKTwFOlX9RpE38J1OSf9z0XsM9cuwGHBMWGr"
        self.api_key_live: Optional[str] = None
        self.api_secret_live: Optional[str] = None

    def get_um_base_url(self) -> str:
        """根据是否测试网返回 UM Futures base_url。"""
        return self.base_url_testnet if self.use_testnet else self.base_url_live

    def get_api_key(self) -> str:
        """根据是否测试网返回对应 API Key。"""
        return self.api_key_test if self.use_testnet else self.api_key_live

    def get_api_secret(self) -> str:
        """根据是否测试网返回对应 API Secret。"""
        return self.api_secret_test if self.use_testnet else self.api_secret_live
