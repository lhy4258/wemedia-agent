const base = '/api/v1/media-agent'

export async function json(path, options) {
  const response = await fetch(`${base}${path}`, options)
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

export function streamUrl(workflowId) {
  return `${base}/workflows/${workflowId}/stream`
}
