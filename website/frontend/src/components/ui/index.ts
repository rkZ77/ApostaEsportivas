/*
 * Ponto único de importação dos primitivos.
 *
 * Preferir `import { Button, Panel, EmptyState } from '../components/ui'` a
 * quatro linhas de import por arquivo. Componentes de produto (SuggestionCard,
 * Navbar, FilterPanel) continuam fora daqui: isto é só o vocabulário base.
 */

export { default as Button, IconButton } from './Button'
export type { ButtonProps } from './Button'

export { default as Badge, PlanBadge, PickTypeBadge, ResultBadge, LiveDot } from './Badge'
export type { BadgeTone } from './Badge'

export { default as Card, StatTile, SectionHead } from './Card'
export { default as Panel, PanelHead, PanelRow, PanelList } from './Panel'

export { default as Modal, Drawer, ModalFooter } from './Modal'

export { default as EmptyState, ErrorState } from './EmptyState'
export { default as Skeleton, SkeletonText, SkeletonCard, SkeletonRows, SkeletonPickCard, SkeletonPickGrid } from './Skeleton'
export { default as Spinner, SpinnerBlock } from './Spinner'

export { default as Pagination } from './Pagination'
export { default as Tabs, PillGroup } from './Tabs'
export type { TabItem } from './Tabs'
export { default as Table } from './Table'
export type { Column } from './Table'

export { Input, SearchInput, Select, Textarea } from './Field'
export { default as Tooltip } from './Tooltip'

export { default as Marquee } from './Marquee'
export { default as NumberTicker } from './NumberTicker'
export { default as ShimmerButton } from './ShimmerButton'
