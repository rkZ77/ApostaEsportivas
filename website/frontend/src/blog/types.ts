export interface PostMeta {
  slug: string
  title: string
  description: string
  /** ISO date, YYYY-MM-DD */
  publishedAt: string
  /** minutes */
  readingTime: number
  category: string
  author: {
    name: string
    role: string
  }
}
