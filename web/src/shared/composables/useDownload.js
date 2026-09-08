export function downloadUrl(url, filename, targetDocument = document) {
  const link = targetDocument.createElement('a')
  link.href = url
  link.download = filename
  targetDocument.body.appendChild(link)
  link.click()
  targetDocument.body.removeChild(link)
}

export function downloadBlob(blob, filename, urlApi = URL, targetDocument = document) {
  const objectUrl = urlApi.createObjectURL(blob)
  try {
    downloadUrl(objectUrl, filename, targetDocument)
  } finally {
    urlApi.revokeObjectURL(objectUrl)
  }
}

export function useDownload() {
  return { downloadUrl, downloadBlob }
}
