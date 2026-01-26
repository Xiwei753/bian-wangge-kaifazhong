# STRATEGY_BLUEPRINT_FINAL.py
# ==============================================================================
# 策略核心逻辑全景图：多因子趋势 + 双重防抖 + 动态网格
# 这是一个逻辑演示文件，用于展示策略"大脑"是如何思考的。
# ==============================================================================

from dataclasses import dataclass
from typing import Dict, List, Optional

from peizhi import GridConfig, MarketMode
from zhibiaojisuan import TechnicalIndicators

config = GridConfig()


@dataclass
class StrategyDecision:
    """打包策略输出，供主程序读取"""
    direction: str
    strength: float
    confidence: float
    duration: int
    score: float
    market_mode: MarketMode
    weights: Dict[str, float]
    long_step: float
    short_step: float
    indicators: Dict[str, float]


# ==============================================================================
# [二] 逻辑模块定义 (The Brain)
# ==============================================================================

class Module1_TrendScoring:
    """
    模块一：趋势评分 (客观打分)
    输入：指标数据
    输出：原始分数 & 初步方向
    """
    def run(self, input_data):
        score = 0.0
        details = []

        # 1. 均线交叉 (权重最大)
        if input_data['ema_fast'] > input_data['ema_slow']:
            score += 2.0; details.append("EMA金叉(+2)")
        else:
            score -= 2.0; details.append("EMA死叉(-2)")

        # 2. RSI 位置
        if input_data['rsi'] > 60:
            score += 1.0; details.append("RSI强势(+1)")
        elif input_data['rsi'] < 40:
            score -= 1.0; details.append("RSI弱势(-1)")

        # 3. 动量
        if input_data['momentum'] > 0.5:
            score += 1.0; details.append("动量向上(+1)")
        
        # 4. 布林带位置
        if input_data['price'] > input_data['bb_upper']:
            score += 0.5; details.append("顶破上轨(+0.5)")
            
        print(f"  [1.评分] 因子详情: {', '.join(details)}")
        print(f"  [1.评分] 原始总分: {score}")
        
        # 归一化强度 (0~1)
        raw_strength = min(abs(score) / 5.0, 1.0)
        
        # 初步定方向
        direction = "SIDEWAYS"
        if score >= config.score_bullish:
            direction = "UPTREND"
        elif score <= config.score_bearish:
            direction = "DOWNTREND"

        return direction, raw_strength, score


class Module2_SignalContinuation:
    """
    模块二：信号延续 (时间维度防骗)
    输入：当前信号 + 历史信号
    输出：修正后的强度 & 置信度
    """
    def run(self, current_dir, current_strength, history_state):
        confidence = 1.0
        
        # 场景 A: 信号发生突变 (比如从 震荡 -> 上涨)
        if current_dir != history_state['last_direction']:
            print(f"  [2.延续] ⚠️ 信号突变 ({history_state['last_direction']} -> {current_dir})")
            print(f"  [2.延续] 启动防莽机制：置信度打折，重置持续时间。")
            
            confidence *= config.confidence_penalty # 打7折
            duration = 1
            
        # 场景 B: 信号保持一致
        else:
            duration = history_state['duration'] + 1
            print(f"  [2.延续] ✅ 信号延续中 (持续 {duration} 周期)")
            
            if duration >= 2:
                # 奖励：趋势确认，增强强度
                current_strength *= config.persistence_bonus
                current_strength = min(current_strength, 1.0)
                print(f"  [2.延续] 趋势确认：强度获得加成 -> {current_strength:.2f}")

        return current_strength, confidence, duration


class Module3_MarketModeSwitch:
    """模块三：市场切换 (带防抖滞后阀)"""
    def run(self, score, last_state, volatility_ratio=0.0): # 增加波动率参数
        # 将分数转为强度 0-1
        strength = min(abs(score) / 5.0, 1.0)

        # 动态计算门槛 (波动越大，门槛越高)
        # 基础激活分对应的强度，例如 3.0分/5.0 = 0.6
        base_strength = config.base_activation

        # 进门难 (Entry): 0.6 * 1.2 = 0.72
        threshold_entry = base_strength * (1.0 + volatility_ratio * config.volatility_factor)
        # 出门难 (Exit):  0.6 * 0.9 = 0.54
        threshold_exit  = base_strength * (1.0 - volatility_ratio * 0.1)

        new_state = last_state

        if last_state == MarketMode.CONSOLIDATION:
            # 必须非常强才能进入趋势
            if strength > threshold_entry:
                new_state = MarketMode.TREND
        else: # TREND
            # 必须掉得很多才退回震荡
            if strength < threshold_exit:
                new_state = MarketMode.CONSOLIDATION

        # 打印调试信息
        # print(f"  [3.防抖] 强度:{strength:.2f} 阈值(进/出):{threshold_entry:.2f}/{threshold_exit:.2f} -> {new_state.value}")
        return new_state


class Module4_DynamicWeights:
    """
    模块四：动态权重分配 (关键策略调整)
    输入：市场状态
    输出：BB/ATR/Trend 三者的权重
    """
    def run(self, market_state):
        w_bb = config.weight_bb_default
        w_atr = config.weight_atr_default
        w_trend = config.weight_trend_default
        
        if market_state == MarketMode.CONSOLIDATION:
            print("  [4.权重] 震荡市：使用默认权重 (关注布林带和ATR)。")
            
        elif market_state == MarketMode.TREND:
            print("  [4.权重] 一般趋势：增加趋势权重，降低震荡指标权重。")
            w_trend += 0.3
            w_bb -= 0.15
            w_atr -= 0.15
            
        return w_bb, w_atr, w_trend


class Module5_StepCalculation:
    """模块五：网格步长最终计算 (关联真实波动率)"""
    def run(self, weights, direction, strength, indicators):
        w_bb, w_atr, w_trend = weights
        price = indicators.get('price', 1.0)

        # 1. 计算基于 ATR 的真实建议步长
        atr_value = indicators.get('atr', 0)
        # 如果 ATR=100, Price=10000, Ratio=0.01。
        # 原策略设定 ATR 倍数 (比如 ATR的一半作为半格)
        step_atr_suggestion = (atr_value / price) * 0.5 if price > 0 else 0.004
        # 限制在合理范围内 (0.1% - 1%)
        step_atr_suggestion = max(0.001, min(step_atr_suggestion, 0.01))

        # 2. 计算基于布林带的建议步长 (带宽越大步长越大)
        upper = indicators.get('bb_upper', 0)
        # 这里简化计算，假设中轨约等于 price
        if upper > 0 and price > 0:
            bb_width = (upper - price) / price # 半带宽
            step_bb_suggestion = bb_width * 0.5
        else:
            step_bb_suggestion = 0.004
        step_bb_suggestion = max(0.001, min(step_bb_suggestion, 0.01))

        # 3. 趋势因子步长 (趋势越强，基础网格稍微放宽防被套，后面再由 compress 压缩)
        step_trend_suggestion = 0.005 * (1 + strength)

        # 加权
        base_step = (step_bb_suggestion * w_bb) + \
                    (step_atr_suggestion * w_atr) + \
                    (step_trend_suggestion * w_trend)

        print(f"  [5.步长] 加权基础步长: {base_step:.4%}")
        
        # 2. 顺势/逆势 非对称调整
        long_step = base_step
        short_step = base_step
        
        if direction == "UPTREND":
            # 顺势(买單)：加密，為了多上車
            compress = 1.0 - (strength * config.trend_compression_max)
            long_step *= compress
            
            # 逆势(卖单)：加宽，防卖飞/防早空
            expand = 1.0 + (strength * config.counter_expansion_max)
            short_step *= expand
            
            print(f"  [5.步长] ⬆️ 上涨模式调整:")
            print(f"     -> 买单(顺): {long_step:.4%} (加密x{compress:.2f})")
            print(f"     -> 卖单(逆): {short_step:.4%} (加宽x{expand:.2f})")
            
        elif direction == "DOWNTREND":
            # 顺势(卖单)：加密
            compress = 1.0 - (strength * config.trend_compression_max)
            short_step *= compress
            
            # 逆势(买单)：加宽
            expand = 1.0 + (strength * config.counter_expansion_max)
            long_step *= expand
            
            print(f"  [5.步长] ⬇️ 下跌模式调整:")
            print(f"     -> 卖单(顺): {short_step:.4%} (加密x{compress:.2f})")
            print(f"     -> 买单(逆): {long_step:.4%} (加宽x{expand:.2f})")
            
        return long_step, short_step


class AdvancedTrendAnalyzer:
    """主类：管理历史状态并串联各模块"""
    def __init__(self, config_override: Optional[GridConfig] = None):
        global config
        if config_override is not None:
            config = config_override
        self.config = config
        self.module_scoring = Module1_TrendScoring()
        self.module_continuation = Module2_SignalContinuation()
        self.module_market = Module3_MarketModeSwitch()
        self.module_weights = Module4_DynamicWeights()
        self.module_step = Module5_StepCalculation()
        self._history_state = {
            "last_direction": "SIDEWAYS",
            "duration": 0,
            "market_mode": MarketMode.CONSOLIDATION,
        }

    def _build_indicators(self, klines: List[Dict]) -> Dict[str, float]:
        prices = [kline.get("close") for kline in klines]
        ema_fast = TechnicalIndicators.ema(prices, period=12)
        ema_slow = TechnicalIndicators.ema(prices, period=26)
        rsi = TechnicalIndicators.rsi(prices, period=14)
        momentum = TechnicalIndicators.momentum(prices, short_period=5, medium_period=10)
        bb = TechnicalIndicators.bollinger_bands(prices, period=20, std_dev=2)
        atr_value = TechnicalIndicators.atr(klines, period=config.atr_length)
        price = TechnicalIndicators._to_float(prices[-1]) if prices else 0.0

        return {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi": rsi,
            "momentum": momentum["short"],
            "price": price,
            "bb_upper": bb["upper"],
            "atr": atr_value,
        }

    def analyze(self, klines: List[Dict]) -> StrategyDecision:
        indicators = self._build_indicators(klines)
        direction, raw_strength, score = self.module_scoring.run(indicators)

        strength, confidence, duration = self.module_continuation.run(
            direction,
            raw_strength,
            self._history_state,
        )

        vol_ratio = indicators["atr"] / indicators["price"] if indicators["price"] else 0
        market_mode = self.module_market.run(
            score,
            self._history_state["market_mode"],
            volatility_ratio=vol_ratio,
        )
        w_bb, w_atr, w_trend = self.module_weights.run(market_mode)
        long_step, short_step = self.module_step.run(
            (w_bb, w_atr, w_trend),
            direction,
            strength,
            indicators,
        )

        self._history_state = {
            "last_direction": direction,
            "duration": duration,
            "market_mode": market_mode,
        }

        return StrategyDecision(
            direction=direction,
            strength=strength,
            confidence=confidence,
            duration=duration,
            score=score,
            market_mode=market_mode,
            weights={"bb": w_bb, "atr": w_atr, "trend": w_trend},
            long_step=long_step,
            short_step=short_step,
            indicators=indicators,
        )
