# 鹈鹕骑自行车 · Pelican Riding a Bicycle

一个自包含的 **SVG 动画**（纯 SMIL，不依赖 CSS / JavaScript）：
一只戴着骑行帽和红围巾的卡通鹈鹕骑着红色自行车兜风。

## 动画内容

- 双腿**真正蹬踏板**：腿部姿态由两骨骼逆运动学（IK）计算，
  以 16 个关键帧烘焙进 `<animate>` 路径插值
- 车轮辐条、曲柄、牙盘同步转动；链条虚线向相反方向爬动
- 路面虚线滚动，远山、云朵、路边灌木以不同速度视差滚动
- 鹈鹕身体随踩踏节奏上下起伏，头部轻点，围巾飘动
- 太阳光芒缓转、车后速度线与尘土效果

## 文件

| 文件 | 说明 |
| --- | --- |
| `pelican-bicycle.svg` | 动画本体（在浏览器中直接打开即可播放） |
| `index.html` | 预览页 |
| `generate_pelican.py` | 生成器：计算 IK 关键帧并重新生成 SVG |

```bash
python3 generate_pelican.py   # 重新生成 pelican-bicycle.svg
```
