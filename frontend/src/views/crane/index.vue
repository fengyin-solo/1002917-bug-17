<template>
  <section class="page" data-module="crane">
    <header class="page-head">
      <div>
        <h2>起重机械管理</h2>
        <p class="page-desc">
          状态须沿 正常 → 超载运行 → 检验中 → 已停用 顺序推进；停用后须补齐上次年检才能恢复使用，
          列表始终按当前额定起重量从大到小排列。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记起重机</button>
        <button class="btn" type="button" @click="exportRows">导出起重机械清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>起重机状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '起重机编号'">
              <RouterLink class="link" :to="`/crane/${row.id}`">{{ row[column] }}</RouterLink>
            </template>
            <template v-else-if="column === '上次年检'">
              <span v-if="row[column]">{{ row[column] }}</span>
              <span v-else class="warn-text" title="未记录年检日期，停用后将无法恢复使用">缺年检日期</span>
            </template>
            <template v-else-if="column === '起重机状态'">
              <span :class="['status-tag', statusClass(row.status)]">{{ row.status ?? '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in allowedActions(row.status)"
              :key="action.name"
              class="link"
              type="button"
              @click="runAction(action.name, row)"
            >
              {{ action.name }}
            </button>
            <button class="link" type="button" @click="openEdit(row)">修改台账</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无起重机械数据，可先登记起重机</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条起重机械记录 · 列表按额定起重量从大到小排序</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-else-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <CraneForm :open="formOpen" :entry="editing" @close="formOpen = false" @saved="onSaved" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import CraneForm, { type CraneFormValues } from './CraneForm.vue'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/crane'
const columns = ["起重机编号", "起重机类型", "额定起重量", "跨度", "工作级别", "操作人员", "上次年检", "起重机状态"]
const statuses = ["正常", "超载运行", "检验中", "已停用"]

// 每个状态下允许的动作：只能顺着状态序列往下走一步；
// 已停用不再给检验入口，只能补齐年检后恢复使用。
const NEXT_ACTION: Record<string, { name: string }[]> = {
  正常: [{ name: '降载运行' }],
  超载运行: [{ name: '安排检验' }],
  检验中: [{ name: '办理停用' }],
  已停用: [{ name: '恢复使用' }],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({ 起重机编号: '', 起重机类型: '', 额定起重量: '', status: '' })
const filterFields = ['起重机编号', '起重机类型', '额定起重量']

const formOpen = ref(false)
const editing = ref<CraneFormValues | null>(null)

const stats = computed(() => {
  const count = (status: string) => rows.value.filter((row) => row.status === status).length
  return [
    { label: '正常起重机', value: count('正常') },
    { label: '超载起重机', value: count('超载运行') },
    { label: '检验中起重机', value: count('检验中') },
    { label: '已停用起重机', value: count('已停用') },
  ]
})

function allowedActions(status: string | number | null) {
  return NEXT_ACTION[String(status ?? '')] ?? []
}

function statusClass(status: string | number | null) {
  return {
    正常: 'st-ok',
    超载运行: 'st-warn',
    检验中: 'st-info',
    已停用: 'st-off',
  }[String(status ?? '')] ?? ''
}

function resetFilters() {
  filters.value = { 起重机编号: '', 起重机类型: '', 额定起重量: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  editing.value = null
  formOpen.value = true
}

function openEdit(row: Row) {
  editing.value = { id: Number(row.id), ...(row as Record<string, string>) }
  formOpen.value = true
}

function onSaved(message: string) {
  formOpen.value = false
  errorMessage.value = ''
  noticeMessage.value = message
  void reload()
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = (await response.json()) as { ok?: boolean; message?: string }
    if (!response.ok || payload.ok === false) {
      // 后端的拦截原因（跳序、停用后安排检验、缺年检）要原样透出，不能只说“操作失败”。
      throw new Error(payload.message || '起重机械动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message || ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机械操作失败'
  }
}

async function reload() {
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value)),
  ).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('起重机列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机械列表读取失败'
  }
}

onMounted(reload)
</script>
