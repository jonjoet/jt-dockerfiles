export function configurationIdentity(path) {
  const parts = path ? path.split('/') : []
  return {
    name: parts.pop() || 'Root configuration',
    folderPath: parts.join('/'),
  }
}

export function folderLabel(folderPath) {
  return folderPath || '/'
}

export function groupedConfigurations(configurations, query) {
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visible = configurations
    .filter(configuration => configuration.path.toLocaleLowerCase().includes(normalizedQuery))
    .sort((left, right) =>
      left.folderPath.localeCompare(right.folderPath) || left.name.localeCompare(right.name),
    )
  const groups = []

  for (const configuration of visible) {
    let group = groups.at(-1)
    if (!group || group.folderPath !== configuration.folderPath) {
      group = { folderPath: configuration.folderPath, items: [] }
      groups.push(group)
    }
    group.items.push(configuration)
  }

  return { visible, groups }
}
