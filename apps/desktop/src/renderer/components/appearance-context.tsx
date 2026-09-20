import { createContext, useContext } from 'react'
import * as THREE from 'three'

export type AppearancePalette = {
  primary: string
  secondary: string
  accent: string
  floor: string
}

export type AppearanceLook = {
  map: THREE.Texture | null
  roofMap: THREE.Texture | null
  matrix: THREE.Matrix4 | null
  palette: AppearancePalette | null
  splatUrl: string | null
  apply: boolean
}

export const AppearanceContext = createContext<AppearanceLook>({
  map: null,
  roofMap: null,
  matrix: null,
  palette: null,
  splatUrl: null,
  apply: false,
})

export function useAppearance() {
  return useContext(AppearanceContext)
}
