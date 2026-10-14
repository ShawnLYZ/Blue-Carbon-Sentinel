export interface TabItem {
  id: string
  label: string
}

export interface TabsProps {
  tabs: TabItem[]
  active: string
  onChange: (id: string) => void
}

export function Tabs({ tabs, active, onChange }: TabsProps) {
  return (
    <div className="bcs-tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          className="bcs-tab"
          aria-selected={t.id === active}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
