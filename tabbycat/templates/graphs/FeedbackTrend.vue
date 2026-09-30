<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  cellData: Object,
  width: { type: Number, default: 425 },
  height: { type: Number, default: 65 },
  padding: { type: Number, default: 20 },
})

const graphData = computed(() => props.cellData?.graphData || [])
const graphElement = ref(null)
let tooltip

function render () {
  if (!graphElement.value) return
  const root = d3.select(graphElement.value)
  root.selectAll('svg').remove()
  tooltip?.remove()
  tooltip = undefined

  const data = graphData.value
  const { baseScore, minScore, maxScore, roundSeq, scoreStep } = props.cellData || {}
  if (!Array.isArray(data) || !roundSeq || minScore >= maxScore) return

  const xScale = d3.scaleLinear().domain([0, roundSeq]).range([0, props.width])
  const yScale = d3.scaleLinear().domain([minScore, maxScore]).range([props.height, 0])
  const svg = root.append('svg')
    .attr('width', props.width + 2 * props.padding)
    .attr('height', props.height + 2 * props.padding)
    .attr('role', 'img')
    .attr('aria-label', 'Feedback by round: dots are round averages, solid line is cumulative average, dashed line is base score')
    .append('g')
    .attr('transform', `translate(${props.padding},${props.padding})`)

  svg.append('g')
    .attr('class', 'x axis')
    .attr('transform', `translate(0,${props.height})`)
    .call(d3.axisBottom(xScale).tickValues(d3.range(1, roundSeq + 1))
      .tickSizeInner(-props.height).tickSizeOuter(0)
      .tickFormat(d => (d === 1 || d === roundSeq ? `R${d}` : '')))

  const step = Number(scoreStep)
  const tickCount = Number.isFinite(step) && step > 0
    ? Math.ceil((maxScore - minScore) / step)
    : 0
  const stride = Math.max(1, Math.ceil(tickCount / 4))
  const yTicks = [minScore]
  if (tickCount && tickCount < 10000) {
    for (let i = stride; i < tickCount; i += stride) {
      yTicks.push(Math.min(maxScore, minScore + i * step))
    }
  }
  yTicks.push(maxScore)
  svg.append('g')
    .attr('class', 'y axis')
    .call(d3.axisLeft(yScale).tickValues(yTicks).tickSizeInner(-props.width)
      .tickSizeOuter(0).tickFormat(d => (d === minScore || d === maxScore ? d3.format('~g')(d) : '')))

  if (baseScore !== null && baseScore !== undefined) {
    svg.append('line')
      .attr('class', 'feedback-base-line')
      .attr('x1', xScale(0)).attr('x2', xScale(roundSeq))
      .attr('y1', yScale(baseScore)).attr('y2', yScale(baseScore))
      .attr('stroke', '#6c757d').attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '4 3')
    svg.append('title').text(`Base score: ${baseScore}`)
  }

  if (!data.length) return
  const sorted = [...data].sort((a, b) => a.x - b.x)
  svg.append('path')
    .datum(sorted)
    .attr('class', 'feedback-cumulative-line')
    .attr('fill', 'none')
    .attr('stroke', '#2874a6')
    .attr('stroke-width', 2)
    .attr('d', d3.line().x(d => xScale(d.x)).y(d => yScale(d.cumulative))
      .curve(d3.curveStepAfter))

  tooltip = d3.select('body').append('div')
    .attr('class', 'd3-tooltip tooltip')
    .style('opacity', 0)

  svg.selectAll('.feedback-round-point').data(sorted).enter().append('circle')
    .attr('class', d => `feedback-round-point hoverable position-display d3-hover-black ${d.position_class || ''}`)
    .attr('cx', d => xScale(d.x))
    .attr('cy', d => yScale(d.y))
    .attr('r', d => Math.min(6, 3.5 + Math.sqrt(d.count) / 2))
    .attr('stroke', d => (d.tested ? '#000' : null))
    .attr('stroke-width', d => (d.tested ? 2 : null))
    .on('pointerenter pointermove', (event, d) => {
      const role = d.position ? ` as ${d.position}` : ''
      const tested = d.tested ? ' (tested)' : ''
      tooltip.style('opacity', 0.95)
        .style('left', `${event.pageX}px`)
        .style('top', `${event.pageY - 28}px`)
        .selectAll('.tooltip-inner').data([d]).join('div')
        .attr('class', 'tooltip-inner')
        .text(`R${d.x}${role}${tested}: average ${d.y} from ${d.count} feedback; cumulative ${d.cumulative} from ${d.cumulative_count} feedback`)
    })
    .on('pointerleave', () => tooltip.style('opacity', 0))
}

onMounted(render)
watch(() => props.cellData, render, { deep: true })
onBeforeUnmount(() => tooltip?.remove())
</script>

<template>
  <td class="unpadded-cell">
    <div ref="graphElement" class="d3-graph d3-feedback-trend" />
  </td>
</template>
