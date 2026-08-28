import { darkTheme } from 'naive-ui'

/** 精致工业风：墨绿主色 + 米白底，圆角/阴影/字重微调。Naive UI themeOverrides。 */
export const naiveThemeOverrides = {
  common: {
    primaryColor: '#4a6b4a',
    primaryColorHover: '#5d815d',
    primaryColorPressed: '#3b563b',
    primaryColorSuppl: '#739074',
    infoColor: '#4a6b4a',
    successColor: '#5d8f5a',
    warningColor: '#d9a43c',
    errorColor: '#c9544e',
    borderRadius: '8px',
    borderRadiusSmall: '6px',
    fontWeightStrong: '600',
  },
  Button: {
    borderRadiusMedium: '8px',
    fontWeight: '500',
  },
  Card: { borderRadius: '10px' },
  DataTable: { borderRadius: '8px', thColor: 'rgba(74,107,74,0.06)' },
  Menu: { itemHeight: '42px', borderRadius: '8px' },
  Tag: { borderRadius: '6px' },
}

export { darkTheme }
