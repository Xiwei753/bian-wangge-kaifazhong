#指标计算，变量名和函数名不管，以后在改，导入以后再改
#然后从sdk获取盘口数据，手动构建k线数据，然后用“binance sdk.py”api查询一下交易所的k线数据，以交易所数据为准。
# technical_indicators.py
import numpy as np
from typing import List, Dict

class TechnicalIndicators:
    """技术指标计算"""
    
    @staticmethod
    def ema(prices: List[float], period: int) -> float:
        """指数移动平均"""
        if len(prices) < period:
            return np.mean(prices) if prices else 0
        
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        return np.convolve(prices[-period:], weights, mode='valid')[-1]
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """相对强弱指数"""
        if len(prices) < period + 1:
            return 50
        
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gains = np.mean(gains[-period:])
        avg_losses = np.mean(losses[-period:])
        
        if avg_losses == 0:
            return 100
        
        rs = avg_gains / avg_losses
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def atr(klines: List[Dict], period: int = 14) -> float:
        """平均真实波幅"""
        if len(klines) < period + 1:
            return 0
        
        tr_values = []
        for i in range(1, len(klines)):
            high = klines[i]['high']
            low = klines[i]['low']
            prev_close = klines[i-1]['close']
            
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            tr = max(tr1, tr2, tr3)
            tr_values.append(tr)
        
        return np.mean(tr_values[-period:]) if tr_values else 0
    
    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: int = 2) -> Dict[str, float]:
        """布林带"""
        if len(prices) < period:
            sma = np.mean(prices) if prices else 0
            return {'upper': sma, 'middle': sma, 'lower': sma}
        
        recent_prices = prices[-period:]
        sma = np.mean(recent_prices)
        std = np.std(recent_prices)
        
        return {
            'upper': sma + (std * std_dev),
            'middle': sma,
            'lower': sma - (std * std_dev)
        }
    
    @staticmethod
    def momentum(prices: List[float], short_period: int = 5, medium_period: int = 10) -> Dict[str, float]:
        """动量分析"""
        if len(prices) < medium_period + 1:
            return {'short': 0, 'medium': 0}
        
        momentum_short = (prices[-1] - prices[-short_period]) / prices[-short_period] * 100
        momentum_medium = (prices[-1] - prices[-medium_period]) / prices[-medium_period] * 100
        
        return {'short': momentum_short, 'medium': momentum_medium}