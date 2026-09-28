import assert from 'node:assert/strict'
import test from 'node:test'

import {
  configurationIdentity,
  folderLabel,
  groupedConfigurations,
} from '../site/static/catalog.js'

test('configuration identities keep root and named folders distinct', () => {
  assert.deepEqual(configurationIdentity('top-level.jbrowse'), {
    name: 'top-level.jbrowse',
    folderPath: '',
  })
  assert.deepEqual(configurationIdentity('Bundle root/nested.jbrowse'), {
    name: 'nested.jbrowse',
    folderPath: 'Bundle root',
  })
  assert.deepEqual(configurationIdentity(''), {
    name: 'Root configuration',
    folderPath: '',
  })
  assert.equal(folderLabel(''), '/')
  assert.equal(folderLabel('Bundle root'), 'Bundle root')
})

test('grouping sorts folders and bundle names without merging root paths', () => {
  const configurations = [
    { path: 'example/b.jbrowse', folderPath: 'example', name: 'b.jbrowse' },
    { path: 'Bundle root/nested.jbrowse', folderPath: 'Bundle root', name: 'nested.jbrowse' },
    { path: 'top-level.jbrowse', folderPath: '', name: 'top-level.jbrowse' },
    { path: 'example/a.jbrowse', folderPath: 'example', name: 'a.jbrowse' },
  ]

  const { visible, groups } = groupedConfigurations(configurations, '')

  assert.equal(visible.length, 4)
  assert.deepEqual(
    groups.map(group => [group.folderPath, group.items.map(item => item.name)]),
    [
      ['', ['top-level.jbrowse']],
      ['Bundle root', ['nested.jbrowse']],
      ['example', ['a.jbrowse', 'b.jbrowse']],
    ],
  )
})

test('filtering matches the full discovered path', () => {
  const configurations = [
    { path: 'first/jbrowse/a.jbrowse', folderPath: 'first/jbrowse', name: 'a.jbrowse' },
    { path: 'second/jbrowse/b.jbrowse', folderPath: 'second/jbrowse', name: 'b.jbrowse' },
  ]

  const { visible, groups } = groupedConfigurations(configurations, 'SECOND')

  assert.deepEqual(visible.map(item => item.name), ['b.jbrowse'])
  assert.deepEqual(groups.map(group => group.folderPath), ['second/jbrowse'])
})
