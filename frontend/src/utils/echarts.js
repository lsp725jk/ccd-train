// echarts 按需引入（模块化）：全量包 ~1.1MB → 按需 ~400KB
// 新增图表类型/组件时在此注册
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart,
  GridComponent, LegendComponent, TitleComponent, TooltipComponent,
  CanvasRenderer,
])

export default echarts
