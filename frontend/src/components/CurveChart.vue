<script setup>
import { onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
})

const el = ref(null)
let chart = null

function render() {
  if (!chart || !props.columns.length || !props.rows.length) return
  const epochIdx = props.columns.indexOf('epoch')
  const x = props.rows.map(r => r[epochIdx])
  const series = props.columns
    .map((c, i) => ({ c, i }))
    .filter(({ i }) => i !== epochIdx && i !== 0)
    .map(({ c, i }) => ({
      name: c,
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 1.5 },
      data: props.rows.map(r => r[i]),
    }))
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 46, right: 16, top: 30, bottom: 34 },
    xAxis: { type: 'category', data: x, name: 'epoch', nameTextStyle: { fontSize: 11 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#e8e6dc' } } },
    series,
  }, { notMerge: true })
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  window.addEventListener('resize', () => chart?.resize())
})

watch(() => [props.columns, props.rows], render, { deep: true })
</script>

<template>
  <div ref="el" style="width: 100%; height: 320px"></div>
</template>
