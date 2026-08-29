<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import echarts from '../utils/echarts'
import { isDark, onThemeChange } from '../utils/theme'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
})

const el = ref(null)
let chart = null
let offTheme = null

function splitColor() {
  return isDark() ? '#3a423c' : '#e8e6dc'
}

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
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 46, right: 16, top: 30, bottom: 34 },
    xAxis: { type: 'category', data: x, name: 'epoch', nameTextStyle: { fontSize: 11 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: splitColor() } } },
    series,
  }, { notMerge: true })
}

function init() {
  chart?.dispose()
  chart = echarts.init(el.value, isDark() ? 'dark' : undefined)
  render()
}

function onResize() { chart?.resize() }

onMounted(() => {
  init()
  window.addEventListener('resize', onResize)
  offTheme = onThemeChange(() => { init() })
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  offTheme && offTheme()
  chart?.dispose()
  chart = null
})

watch(() => [props.columns, props.rows], render, { deep: true })
</script>

<template>
  <div ref="el" style="width: 100%; height: 320px"></div>
</template>
