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
        self.symbol: str = "SOLUSDC"  # 交易对（合约品种），例：SOLUSDC/BTCUSDC
        self.timeframe_minutes: int = 3  # 交易K线周期（分钟），常见 1/3/5/15/60
        self.initial_capital: float = 10000  # 初始资金（USDC/USDT），用于资金管理或回测
        self.leverage: int = 100  # 杠杆倍数，合约常见 1-125
        self.margin_mode: str = "CROSSED"  # 保证金模式：CROSSED（全仓）或 ISOLATED（逐仓）
        self.grid_step_ratio: float = 0.002  # 网格间距比例（相对价格），如 0.002=0.2%
        self.long_open_short_tp_step_ratio: float = 0.002  # 多开后空单止盈步长比例
        self.short_open_long_tp_step_ratio: float = 0.002  # 空开后多单止盈步长比例
        self.market_mode: MarketMode = MarketMode.CONSOLIDATION  # 市场模式：震荡(consolidation)或趋势(trend)
        self.price_precision: int = 2  # 价格精度（小数位数），例如 1 表示 0.1
        self.qty_precision: int = 2  # 数量精度（小数位数），例如 2 表示 0.01

        # ===================== 趋势评分配置 =====================
        self.score_bullish: float = 3.0  # 看多得分阈值，用于趋势判定
        self.score_bearish: float = -3.0  # 看空得分阈值，用于趋势判定

        # ===================== 信号延续配置 =====================
        self.confidence_penalty: float = 0.7  # 信号不确定性惩罚系数（越小惩罚越大）
        self.persistence_bonus: float = 1.1  # 信号持续性加成系数（>1 加强持续信号）

        # ===================== 状态切换阈值配置 =====================
        self.base_activation: float = 0.6  # 状态切换基础阈值（0-1）
        self.volatility_factor: float = 0.2  # 波动率对切换阈值的影响因子

        # ===================== 动态权重配置 =====================
        self.weight_bb_default: float = 0.4  # Bollinger 权重（基础值）
        self.weight_atr_default: float = 0.4  # ATR 权重（基础值）
        self.weight_trend_default: float = 0.2  # 趋势权重（基础值）

        # ===================== 网格调整配置 =====================
        self.trend_compression_max: float = 0.4  # 趋势模式下网格压缩最大比例
        self.counter_expansion_max: float = 1.0  # 逆势模式下网格扩张最大比例
        
        # ===================== 功能开关配置 =====================
        self.enable_wechat_push: bool = True  # 是否启用企业微信推送（开多/开空/止盈等交易事件）
        self.wechat_webhook_url: str = (
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=43874765-eb79-481d-84ce-3773b1e879d7"
            # 企业微信机器人Webhook（示例说明）：
            # - 开仓方向：开多/开空
            # - 价格与数量：成交价格、下单数量
            # - 止盈结果：本次止盈吃掉的百分比（如 0.3%/0.5%）
            # - 趋势原因：进入趋势市的触发条件（如趋势强度/波动率阈值达标）
            # - 可信度与强度：信号可信度与趋势强度数值
        )
        self.enable_short: bool = True  # 是否允许开空
        self.enable_flexible_tp: bool = True  # 是否启用动态止盈
        self.enable_profit_stop_for_trapped: bool = True  # 套牢仓位是否启用止盈保护

        # ===================== 网格基础参数 =====================
        self.grid_count: int = 3  # 网格层数（每侧挂单数量）
        self.fixed_order_size: float = 0.06  # 每次下单币数量（例：SOL 数量）
        self.position_report_interval: int = 180  # 仓位报告间隔（秒）
        
        # ===================== 动态网格管理配置 =====================
        self.consolidation_step_min_ratio: float = 0.001  # 震荡市最小网格间距
        self.consolidation_step_max_ratio: float = 0.006  # 震荡市最大网格间距
        self.trend_follow_step_min_ratio: float = 0.001  # 顺势最小网格间距
        self.trend_follow_step_max_ratio: float = 0.003  # 顺势最大网格间距
        self.counter_trend_step_min_ratio: float = 0.004  # 逆势最小网格间距
        self.counter_trend_step_max_ratio: float = 0.01  # 逆势最大网格间距
        self.trend_activation_threshold: float = 0.6  # 进入趋势模式阈值（0-1）
        self.extreme_trend_threshold: float = 0.8  # 极端趋势阈值（用于加速处理）
        self.volatility_spike_threshold: float = 2.0  # 波动率激增阈值（倍数）
        self.redeploy_price_threshold: float = 0.02  # 价格偏离触发重新布网比例
        self.redeploy_step_change_threshold: float = 0.5  # 网格步长变化触发布网阈值
        self.trend_change_cooldown: int = 300  # 趋势切换冷却时间（秒）
        
        # ===================== 动态权重配置 =====================
        self.base_bollinger_weight: float = 0.4  # Bollinger 基础权重
        self.base_atr_weight: float = 0.4  # ATR 基础权重
        self.base_trend_weight: float = 0.2  # 趋势基础权重
        
        # ===================== 趋势乘数配置 =====================
        self.trend_follow_multiplier_min: float = 0.1  # 顺势倍数下限
        self.trend_follow_multiplier_max: float = 1.0  # 顺势倍数上限
        self.counter_trend_multiplier_min: float = 1.0  # 逆势倍数下限
        self.counter_trend_multiplier_max: float = 3.0  # 逆势倍数上限
        
        # ===================== 仓位调整配置 =====================
        self.position_adjustment_range: float = 0.03  # 仓位调整范围（相对价格）
        self.tp_adjustment_cooldown: int = 60  # 止盈调整冷却时间（秒）
        
        # ===================== 止盈配置 =====================
        self.trend_follow_tp_base_ratio: float = 0.004  # 顺势止盈基础比例
        self.trend_follow_tp_boost_max: float = 0.008  # 顺势止盈加成上限
        self.counter_trend_tp_min_ratio: float = 0.001  # 逆势止盈最小比例
        self.counter_trend_tp_base_ratio: float = 0.002  # 逆势止盈基础比例
        self.consolidation_tp_ratio: float = 0.003  # 震荡市止盈比例
        self.normal_tp_ratio: float = 0.002  # 常规止盈比例
        self.min_tp_ratio: float = 0.001  # 最小止盈比例（保底）
        self.counter_trend_tp_ratio: float = 0.0015  # 逆势默认止盈比例
        
        # ===================== 网格间距系数 =====================
        self.trend_follow_spacing_min: float = 0.3  # 顺势网格间距系数下限
        self.trend_follow_spacing_max: float = 0.8  # 顺势网格间距系数上限
        self.counter_trend_spacing_min: float = 1.5  # 逆势网格间距系数下限
        self.counter_trend_spacing_max: float = 3.0  # 逆势网格间距系数上限
        self.consolidation_spacing: float = 1.0  # 震荡市网格间距系数
        
        # ===================== 技术指标参数 =====================
        self.atr_length: int = 14  # ATR 计算周期
        self.atr_mult_normal: float = 20.0  # 常规 ATR 倍数
        self.atr_mult_attack: float = 6.0  # 攻击/快速模式 ATR 倍数
        self.min_grid_step_ratio: float = 0.004  # 网格间距下限比例
        
        # ===================== 趋势适应参数 =====================
        self.trend_adjustment_factor: float = 0.3  # 趋势调整因子（影响网格/止盈）
        self.min_trend_strength: int = 20  # 最小趋势强度（注意单位/算法）
        self.consolidation_atr_ratio: float = 0.3  # 震荡市 ATR 比例阈值
        
        # ===================== 网格优化参数 =====================
        self.aggressive_grid_count: int = 5  # 激进模式网格层数
        self.defensive_grid_count: int = 3  # 防守模式网格层数
        self.trend_grid_spacing: float = 1.5  # 趋势网格间距系数
        self.counter_trend_grid_spacing: float = 2.5  # 逆势网格间距系数
        
        # ===================== 信号延续参数 =====================
        self.signal_confirmation_periods: int = 2  # 信号确认周期数
        self.min_signal_strength: float = 0.6  # 最小信号强度阈值
        
        # ===================== 波动率参数 =====================
        self.volatility_lookback: int = 10  # 波动率回看周期数
        self.min_volatility_ratio: float = 0.3  # 最小波动率比例阈值
        
        # ===================== 趋势过滤参数 =====================
        self.min_trend_strength: float = 0.6  # 最小趋势强度（0-1，注意与上方同名参数不同）
        self.min_trend_confidence: float = 0.6  # 最小趋势置信度（0-1）
        self.min_trend_duration: int = 2  # 最小趋势持续周期数
        
        # ===================== 套牢仓位参数 =====================
        self.trapped_position_range: float = 0.03  # 套牢判断范围（相对价格）
        
        # ===================== 智能响应配置 =====================
        self.max_deploy_frequency_5min: int = 8  # 5分钟内最大部署次数（防止频繁重布）
        self.emergency_volume_multiplier: float = 3.0  # 紧急情况成交量倍数阈值
        self.emergency_price_change: float = 0.02  # 紧急情况价格变动阈值（相对比例）
        
        # ===================== 动态阈值配置 =====================
        self.high_volatility_threshold: float = 0.03  # 高波动率阈值
        self.medium_volatility_threshold: float = 0.015  # 中等波动率阈值
        self.low_volatility_strength_threshold: float = 0.5  # 低波动率趋势强度阈值
        self.medium_volatility_strength_threshold: float = 0.6  # 中等波动率趋势强度阈值
        self.high_volatility_strength_threshold: float = 0.7  # 高波动率趋势强度阈值
        
        # ===================== API配置 =====================
        # Binance Python Connector (USDT-M 合约)
        self.api_key: str = ""  # 兼容字段：可直接填写（优先级由具体实现决定）
        self.api_secret: str = ""  # 兼容字段：可直接填写（优先级由具体实现决定）
        self.use_testnet: bool = True  # 是否使用测试网（True=测试网，False=主网）
        self.base_url_testnet: str = "https://testnet.binancefuture.com"  # 测试网地址
        self.base_url_live: str = "https://fapi.binance.com"  # 主网地址
        self.recv_window: int = 5000  # 请求有效窗口（毫秒）
        self.request_timeout: int = 10  # 请求超时时间（秒）
        self.api_key_test: Optional[str] = "GpTMMRi3M92kZGFUErS7UfS2vl0TaBzgNtb1lWIhjIwaIsGcd4PrAcu3eRTsmcdJ"  # 测试网 API Key
        self.api_secret_test: Optional[str] = "fpPn45zFzRoBxKBpcJiQjkjkrzhQVKTwFOlX9RpE38J1OSf9z0XsM9cuwGHBMWGr"  # 测试网 Secret
        self.api_key_live: Optional[str] = None  # 主网 API Key（请自行填写）
        self.api_secret_live: Optional[str] = None  # 主网 Secret（请自行填写）

    def get_um_base_url(self) -> str:
        """根据是否测试网返回 UM Futures base_url。"""
        return self.base_url_testnet if self.use_testnet else self.base_url_live

    def get_api_key(self) -> str:
        """根据是否测试网返回对应 API Key。"""
        return self.api_key_test if self.use_testnet else self.api_key_live

    def get_api_secret(self) -> str:
        """根据是否测试网返回对应 API Secret。"""
        return self.api_secret_test if self.use_testnet else self.api_secret_live


