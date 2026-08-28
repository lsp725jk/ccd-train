<script setup>
import { NEmpty, NImage, NImageGroup } from 'naive-ui'

defineProps({
  result: { type: Object, default: null },
})
</script>

<template>
  <div>
    <template v-if="result">
      <div v-if="Object.keys(result.metrics).length" class="metric-grid">
        <div v-for="(v, k) in result.metrics" :key="k" class="metric">
          <div class="metric-value">{{ v }}</div>
          <div class="metric-label">{{ k }}</div>
        </div>
      </div>
      <div v-if="result.viz.length" style="margin-top:12px">
        <div style="font-size:0.85rem;color:#4a433c;margin-bottom:8px">可视化</div>
        <n-image-group>
          <div class="viz-grid">
            <n-image v-for="v in result.viz" :key="v" :src="v" object-fit="contain" class="viz-img" />
          </div>
        </n-image-group>
      </div>
    </template>
    <n-empty v-else description="训练完成后展示指标、混淆矩阵与预测画廊" :image-size="60" />
  </div>
</template>

<style scoped>
.metric-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
}
.metric { min-width: 100px; }
.metric-value { font-size: 1.3rem; font-weight: 600; color: #4a6b4a; font-variant-numeric: tabular-nums; }
.metric-label { font-size: 0.75rem; color: #8a8175; }
.viz-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
/* n-image 内部 img 需强制填满容器（按原始尺寸渲染只会露出角落），object-fit 保持 contain */
.viz-img { width: 100%; height: 160px; border: 1px solid #d8cfbe; border-radius: 4px; overflow: hidden; }
.viz-img :deep(img) { width: 100% !important; height: 100% !important; object-fit: contain; display: block; }
</style>
