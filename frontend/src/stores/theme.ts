import { defineStore } from 'pinia'

export const useThemeStore = defineStore('theme', {
  state: () => ({
    dark: localStorage.getItem('slide-note-theme') === 'dark'
  }),
  actions: {
    apply() {
      document.documentElement.classList.toggle('dark', this.dark)
      localStorage.setItem('slide-note-theme', this.dark ? 'dark' : 'light')
    },
    toggle(value: boolean) {
      this.dark = value
      this.apply()
    }
  }
})

