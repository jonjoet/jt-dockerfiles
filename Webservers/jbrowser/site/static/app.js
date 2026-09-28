import { configurationIdentity, folderLabel, groupedConfigurations } from './catalog.js'

const bundleRoot = new URL('bundles/', document.baseURI)
const appRoot = new URL('app/', document.baseURI)
const directoryLimit = 10000

const refreshButton = document.querySelector('#refresh')
const searchInput = document.querySelector('#search')
const status = document.querySelector('#status')
const groupsContainer = document.querySelector('#configuration-groups')

let configurations = []
let loading = false

function validEntry(entry) {
  return entry
    && typeof entry.name === 'string'
    && entry.name.length > 0
    && entry.name !== '.'
    && entry.name !== '..'
    && !entry.name.includes('/')
    && !entry.name.includes('\\')
}

function childUrl(parent, name, directory = false) {
  return new URL(`${encodeURIComponent(name)}${directory ? '/' : ''}`, parent)
}

async function listDirectory(url) {
  const response = await fetch(url, {
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`Could not list ${url.pathname}: HTTP ${response.status}`)
  }
  const entries = await response.json()
  if (!Array.isArray(entries)) {
    throw new Error(`Directory listing at ${url.pathname} was not a JSON array`)
  }
  return entries.filter(validEntry)
}

async function discoverConfigurations() {
  const found = []
  const queue = [{ url: bundleRoot, path: '', modified: null }]
  let visited = 0

  while (queue.length > 0) {
    if (++visited > directoryLimit) {
      throw new Error(`Stopped after ${directoryLimit.toLocaleString()} directories`)
    }

    const current = queue.shift()
    const entries = await listDirectory(current.url)
    const config = entries.find(entry => entry.type === 'file' && entry.name === 'config.json')

    if (config) {
      found.push({
        path: current.path || '.',
        ...configurationIdentity(current.path),
        configUrl: childUrl(current.url, config.name),
        modified: config.mtime || current.modified,
      })
      continue
    }

    for (const entry of entries) {
      if (entry.type !== 'directory' || entry.name.startsWith('.')) {
        continue
      }
      queue.push({
        url: childUrl(current.url, entry.name, true),
        path: current.path ? `${current.path}/${entry.name}` : entry.name,
        modified: entry.mtime || null,
      })
    }
  }

  return found
}

function openUrl(configuration) {
  const url = new URL(appRoot)
  url.searchParams.set('config', configuration.configUrl.pathname)
  return url
}

function makeLink(label, href, className = '') {
  const link = document.createElement('a')
  link.textContent = label
  link.href = href
  if (className) {
    link.className = className
  }
  return link
}

function formatModified(value) {
  if (!value) {
    return 'Unknown'
  }
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString()
}

function configurationTable(folderPath, items, index) {
  const section = document.createElement('section')
  const heading = document.createElement('div')
  const title = document.createElement('h2')
  const count = document.createElement('span')
  const tableWrap = document.createElement('div')
  const table = document.createElement('table')
  const tableHead = document.createElement('thead')
  const headingRow = document.createElement('tr')
  const tableBody = document.createElement('tbody')
  const titleId = `bundle-folder-${index}`

  section.className = 'bundle-group'
  section.setAttribute('aria-labelledby', titleId)
  heading.className = 'group-heading'
  title.id = titleId
  title.textContent = folderLabel(folderPath)
  count.className = 'bundle-count'
  count.textContent = `${items.length.toLocaleString()} bundle${items.length === 1 ? '' : 's'}`
  heading.append(title, count)

  for (const label of ['Configuration', 'Modified', 'Actions']) {
    const cell = document.createElement('th')
    cell.scope = 'col'
    cell.textContent = label
    headingRow.append(cell)
  }
  tableHead.append(headingRow)

  for (const configuration of items) {
    const row = document.createElement('tr')
    const name = document.createElement('td')
    const modified = document.createElement('td')
    const actions = document.createElement('td')

    name.textContent = configuration.name
    modified.textContent = formatModified(configuration.modified)
    actions.className = 'actions'
    actions.append(
      makeLink('Open', openUrl(configuration), 'primary'),
      makeLink('config.json', configuration.configUrl),
    )
    row.append(name, modified, actions)
    tableBody.append(row)
  }

  table.append(tableHead, tableBody)
  tableWrap.className = 'table-wrap'
  tableWrap.append(table)
  section.append(heading, tableWrap)
  return section
}

function render() {
  if (loading) {
    return
  }
  const { visible, groups } = groupedConfigurations(configurations, searchInput.value)
  groupsContainer.replaceChildren(
    ...groups.map((group, index) => configurationTable(group.folderPath, group.items, index)),
  )

  if (configurations.length === 0) {
    status.textContent = 'No config.json files were found.'
  } else if (visible.length === configurations.length) {
    status.textContent = `${configurations.length.toLocaleString()} configuration${configurations.length === 1 ? '' : 's'} in ${groups.length.toLocaleString()} folder${groups.length === 1 ? '' : 's'}.`
  } else {
    status.textContent = `${visible.length.toLocaleString()} of ${configurations.length.toLocaleString()} configurations shown in ${groups.length.toLocaleString()} folder${groups.length === 1 ? '' : 's'}.`
  }
}

async function refresh() {
  loading = true
  refreshButton.disabled = true
  status.textContent = 'Loading configurations...'
  groupsContainer.replaceChildren()

  try {
    configurations = await discoverConfigurations()
    loading = false
    render()
  } catch (error) {
    configurations = []
    status.textContent = error instanceof Error ? error.message : String(error)
  } finally {
    loading = false
    refreshButton.disabled = false
  }
}

refreshButton.addEventListener('click', refresh)
searchInput.addEventListener('input', render)

refresh()
