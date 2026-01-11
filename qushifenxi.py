#趋势分析，额，大概长这样，变量名和函数名先不管，先把逻辑写出来
# trend_analyzer.py
import time
import numpy as np
from collections import deque
from typing import List, Dict, Any
from data_structures import MarketSignal, TrendDirection
from technical_indicators import TechnicalIndicators

class AdvancedTrendAnalyzer:
    """高级趋势分析器 - 修复版"""
    
    def __init__(self, config):
        self.config = config
        self.indicators = TechnicalIndicators()
        self.signal_history = deque(maxlen=10)
        self.current_signal = None
        
        # 指标参数
        self.ema_fast_period = 8
        self.ema_slow_period = 21
        self.rsi_period = 14
        self.volume_ema_period = 20
        self.bb_period = 20
        self.bb_std = 2
    
    def analyze_trend(self, klines: List[Dict], realtime: bool = False) -> MarketSignal:
        """分析趋势 - 应用过滤机制"""
        if not klines or len(klines) < 30:
            return self._create_default_signal()
        
        prices = [k['close'] for k in klines]
        volumes = [k.get('volume', 1) for k in klines]
        
        # 计算各项指标
        ema_fast = self.indicators.ema(prices, self.ema_fast_period)
        ema_slow = self.indicators.ema(prices, self.ema_slow_period)
        rsi = self.indicators.rsi(prices, self.rsi_period)
        momentum = self.indicators.momentum(prices)
        bb = self.indicators.bollinger_bands(prices, self.bb_period, self.bb_std)
        
        # 成交量分析
        volume_signal = self._analyze_volume(prices, volumes)
        
        # 综合趋势评分
        trend_score = self._calculate_trend_score(
            ema_fast, ema_slow, rsi, momentum, bb, volume_signal, prices[-1]
        )
        
        # 信号延续确认
        signal = self._confirm_signal_continuation(trend_score, rsi, momentum, realtime)
        
        # 应用趋势过滤
        filtered_signal = self._apply_trend_filter(signal)
        
        return filtered_signal
    
    def _apply_trend_filter(self, signal: MarketSignal) -> MarketSignal:
        """应用趋势过滤机制"""
        # 使用配置中的阈值
        min_strength = self.config.min_trend_strength
        min_confidence = self.config.min_trend_confidence
        
        # 如果趋势强度或置信度不达标，强制设为震荡
        if (signal.direction != TrendDirection.SIDEWAYS and 
            (signal.strength < min_strength or 
             signal.confidence < min_confidence)):
            
            return MarketSignal(
                direction=TrendDirection.SIDEWAYS,
                strength=0,
                confidence=0,
                duration=signal.duration,
                trigger_time=signal.trigger_time,
                indicators=signal.indicators
            )
        
        return signal
    
    def _calculate_trend_score(self, ema_fast: float, ema_slow: float, rsi: float, 
                             momentum: Dict, bb: Dict, volume_signal: float, current_price: float) -> float:
        """计算趋势综合评分"""
        score = 0
        
        # EMA方向
        if ema_fast > ema_slow:
            score += 2
        else:
            score -= 2
        
        # RSI位置
        if rsi > 60:
            score += 1
        elif rsi < 40:
            score -= 1
        
        # 动量
        if momentum['short'] > 0.5:
            score += 1
        elif momentum['short'] < -0.5:
            score -= 1
            
        if momentum['medium'] > 1:
            score += 1.5
        elif momentum['medium'] < -1:
            score -= 1.5
        
        # 布林带位置
        bb_position = (current_price - bb['lower']) / (bb['upper'] - bb['lower'])
        if bb_position > 0.7:
            score += 0.5
        elif bb_position < 0.3:
            score -= 0.5
        
        # 成交量确认
        score += volume_signal
        
        return score
    
    def _analyze_volume(self, prices: List[float], volumes: List[float]) -> float:
        """成交量分析"""
        if len(volumes) < 10:
            return 0
        
        # 计算成交量EMA
        volume_ema = self.indicators.ema(volumes, self.volume_ema_period)
        
        # 价格变化
        price_change = (prices[-1] - prices[-5]) / prices[-5] * 100
        
        # 成交量确认
        if price_change > 0.5 and volumes[-1] > volume_ema * 1.2:
            return 1.0
        elif price_change < -0.5 and volumes[-1] > volume_ema * 1.2:
            return -1.0
        
        return 0
    
    def _confirm_signal_continuation(self, trend_score: float, rsi: float, 
                                   momentum: Dict, realtime: bool) -> MarketSignal:
        """确认信号延续性 - 增加稳定性"""
        # 确定基础方向 - 使用更高的阈值
        if trend_score >= 4:  # 从3提高到4
            direction = TrendDirection.UPTREND
            strength = min((trend_score - 3) / 4, 1.0)  # 调整强度计算
        elif trend_score <= -4:  # 从-3提高到-4
            direction = TrendDirection.DOWNTREND
            strength = min(abs(trend_score + 3) / 4, 1.0)  # 调整强度计算
        else:
            direction = TrendDirection.SIDEWAYS
            strength = 0
        
        # 计算置信度 - 使用更严格的条件
        confidence_factors = 0
        if abs(trend_score) >= 4:  # 从3提高到4
            confidence_factors += 1
        if abs(momentum['medium']) > 2:  # 从1提高到2
            confidence_factors += 1
        if 25 <= rsi <= 75:  # 从30-70放宽到25-75
            confidence_factors += 1
        
        confidence = min(confidence_factors / 3, 1.0)
        
        # 信号延续逻辑 - 增加稳定性
        current_signal = MarketSignal(
            direction=direction,
            strength=strength,
            confidence=confidence,
            duration=1,
            trigger_time=time.time(),
            indicators={'rsi': rsi, 'momentum': momentum, 'trend_score': trend_score}
        )
        
        # 检查信号延续性 - 只有当信号持续时才增强
        if self.current_signal and self.current_signal.direction == direction:
            current_signal.duration = self.current_signal.duration + 1
            # 只有当信号持续至少2个周期时才增强
            if current_signal.duration >= 2:
                current_signal.strength = min(current_signal.strength * 1.1, 1.0)  # 从1.2降低到1.1
                current_signal.confidence = min(current_signal.confidence * 1.05, 1.0)  # 从1.1降低到1.05
        else:
            # 新信号开始时降低置信度
            if not realtime:
                current_signal.confidence *= 0.7  # 从0.8降低到0.7
        
        self.current_signal = current_signal
        self.signal_history.append(current_signal)
        
        return current_signal
    
    def _create_default_signal(self) -> MarketSignal:
        """创建默认信号"""
        return MarketSignal(
            direction=TrendDirection.SIDEWAYS,
            strength=0,
            confidence=0,
            duration=0,
            trigger_time=time.time(),
            indicators={}
        )