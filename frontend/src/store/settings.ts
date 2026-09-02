import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { BaseCurrency } from '../api/types'

interface SettingsState {
  baseCurrency: BaseCurrency
  setBaseCurrency: (c: BaseCurrency) => void
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      baseCurrency: 'CNY',
      setBaseCurrency: (baseCurrency) => set({ baseCurrency }),
    }),
    { name: 'omninav-settings' },
  ),
)
