# STRATEGY_BLUEPRINT_FINAL.py
# ==============================================================================
# 策略核心逻辑全景图：多因子趋势 + 双重防抖 + 动态网格
# 这是一个逻辑演示文件，用于展示策略"大脑"是如何思考的。
# ==============================================================================

import time

# ==============================================================================
# [一] 全局参数配置 (The Rules)
# ==============================================================================
class Config:
    # 1. 评分标准
    SCORE_BULLISH = 3.0    # >3 分看涨
    SCORE_BEARISH = -3.0   # <-3 分看跌
    
    # 2. 信号延续 (防莽夫：防止刚出信号就满仓)
    CONFIDENCE_PENALTY = 0.7  # 新信号第一根K线，置信度打7折
    PERSISTENCE_BONUS = 1.1   # 信号延续多根K线，强度奖励10%
    
    # 3. 状态切换阈值 (防抖动：防止在临界点反复横跳)
    BASE_ACTIVATION = 0.6     # 基础进入趋势的强度门槛
    VOLATILITY_FACTOR = 0.2   # 波动率对门槛的加成系数
    
    # 4. 动态权重 (决定谁主导网格步长)
    # 默认：ATR和布林带各占40%，趋势占20%
    WEIGHT_BB_DEFAULT = 0.4
    WEIGHT_ATR_DEFAULT = 0.4
    WEIGHT_TREND_DEFAULT = 0.2
    
    # 5. 网格调整系数
    TREND_COMPRESSION_MAX = 0.4  # 顺势网格最大加密 40%
    COUNTER_EXPANSION_MAX = 1.0  # 逆势网格最大加宽 100%


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
        if score >= Config.SCORE_BULLISH: direction = "UPTREND"
        elif score <= Config.SCORE_BEARISH: direction = "DOWNTREND"
        
        return direction, raw_strength


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
            
            confidence *= Config.CONFIDENCE_PENALTY # 打7折
            duration = 1
            
        # 场景 B: 信号保持一致
        else:
            duration = history_state['duration'] + 1
            print(f"  [2.延续] ✅ 信号延续中 (持续 {duration} 周期)")
            
            if duration >= 2:
                # 奖励：趋势确认，增强强度
                current_strength *= Config.PERSISTENCE_BONUS
                current_strength = min(current_strength, 1.0)
                print(f"  [2.延续] 趋势确认：强度获得加成 -> {current_strength:.2f}")

        return current_strength, confidence, duration


class Module3_StateHysteresis:
    """
    模块三：双阈值状态机 (Schmitt Trigger 防抖)
    输入：强度 + 波动率 + 上一刻状态
    输出：最终市场状态 (Consolidation/Trending)
    """
    def run(self, strength, volatility_idx, last_state):
        # 1. 计算动态门槛
        # 波动率越大(volatility_idx越大)，门槛越高
        # 进门门槛 (Entry): 比如 0.6 * 1.2 = 0.72
        threshold_entry = Config.BASE_ACTIVATION * (1.0 + volatility_idx * Config.VOLATILITY_FACTOR)
        # 出门门槛 (Exit):  比如 0.6 * 0.8 = 0.48
        threshold_exit  = Config.BASE_ACTIVATION * (1.0 - volatility_idx * 0.1)  
        
        print(f"  [3.防抖] 当前强度: {strength:.2f}")
        print(f"  [3.防抖] 动态门槛: 进门>{threshold_entry:.2f} | 出门<{threshold_exit:.2f}")
        
        new_state = last_state # 默认保持
        
        # 逻辑：进门难，出门难
        if last_state == "CONSOLIDATION":
            if strength > threshold_entry:
                new_state = "TRENDING"
                print("  [3.防抖] 🚀 突破高门槛，切换至 [TRENDING]!")
            else:
                print("  [3.防抖] 未突破高门槛，保持 [CONSOLIDATION]。")
                
        elif last_state == "TRENDING":
            if strength < threshold_exit:
                new_state = "CONSOLIDATION"
                print("  [3.防抖] 📉 跌破低门槛，切换至 [CONSOLIDATION]。")
            else:
                print("  [3.防抖] 未跌破低门槛，维持 [TRENDING]。")
                
        # 判定极端趋势
        if new_state == "TRENDING" and strength > 0.8:
            new_state = "EXTREME_TREND"
            print("  [3.防抖] 🔥 强度爆表，判定为 [EXTREME_TREND]!")
            
        return new_state


class Module4_DynamicWeights:
    """
    模块四：动态权重分配 (关键策略调整)
    输入：市场状态
    输出：BB/ATR/Trend 三者的权重
    """
    def run(self, market_state):
        w_bb = Config.WEIGHT_BB_DEFAULT
        w_atr = Config.WEIGHT_ATR_DEFAULT
        w_trend = Config.WEIGHT_TREND_DEFAULT
        
        if market_state == "CONSOLIDATION":
            print("  [4.权重] 震荡市：使用默认权重 (关注布林带和ATR)。")
            
        elif market_state == "TRENDING":
            print("  [4.权重] 一般趋势：增加趋势权重，降低震荡指标权重。")
            w_trend += 0.3
            w_bb -= 0.15
            w_atr -= 0.15
            
        elif market_state == "EXTREME_TREND":
            print("  [4.权重] 🚨 极端趋势：强制忽略布林带！全力跟随趋势！")
            # 这里的逻辑是你提到的关键点
            w_bb = 0.02    # 2% (几乎忽略)
            w_atr = 0.02   # 2% (几乎忽略)
            w_trend = 0.96 # 96%
            
        return w_bb, w_atr, w_trend


class Module5_StepCalculation:
    """
    模块五：网格步长最终计算
    输入：权重 + 方向 + 强度
    输出：买单步长 & 卖单步长
    """
    def run(self, weights, direction, strength, base_atr_step=0.005):
        w_bb, w_atr, w_trend = weights
        
        # 1. 计算加权基础步长 (为了演示，假设各指标给出的建议值)
        step_bb_suggestion = 0.006
        step_atr_suggestion = 0.004
        step_trend_suggestion = 0.008 # 趋势越强通常建议步长越宽以防被套
        
        base_step = (step_bb_suggestion * w_bb) + \
                    (step_atr_suggestion * w_atr) + \
                    (step_trend_suggestion * w_trend)
                    
        print(f"  [5.步长] 加权基础步长: {base_step:.4%}")
        
        # 2. 顺势/逆势 非对称调整
        long_step = base_step
        short_step = base_step
        
        if direction == "UPTREND":
            # 顺势(买單)：加密，為了多上車
            compress = 1.0 - (strength * Config.TREND_COMPRESSION_MAX)
            long_step *= compress
            
            # 逆势(卖单)：加宽，防卖飞/防早空
            expand = 1.0 + (strength * Config.COUNTER_EXPANSION_MAX)
            short_step *= expand
            
            print(f"  [5.步长] ⬆️ 上涨模式调整:")
            print(f"     -> 买单(顺): {long_step:.4%} (加密x{compress:.2f})")
            print(f"     -> 卖单(逆): {short_step:.4%} (加宽x{expand:.2f})")
            
        elif direction == "DOWNTREND":
            # 顺势(卖单)：加密
            compress = 1.0 - (strength * Config.TREND_COMPRESSION_MAX)
            short_step *= compress
            
            # 逆势(买单)：加宽
            expand = 1.0 + (strength * Config.COUNTER_EXPANSION_MAX)
            long_step *= expand
            
            print(f"  [5.步长] ⬇️ 下跌模式调整:")
            print(f"     -> 卖单(顺): {short_step:.4%} (加密x{compress:.2f})")
            print(f"     -> 买单(逆): {long_step:.4%} (加宽x{expand:.2f})")
            
        return long_step, short_step
