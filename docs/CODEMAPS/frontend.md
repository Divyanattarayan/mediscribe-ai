<!-- Generated: 2026-09-17 | Files scanned: 26 ts/tsx/css (3,654 LOC) | Token estimate: ~700 -->

# Frontend

React 19 + TypeScript + Vite 7 + Tailwind 4. **No router** — `App.tsx` switches
on `currentPage` from the Zustand store. State is one store; server access is one
axios module.

## Page tree

```
main.tsx
└── App.tsx                       restores session from stored JWT first
    ├── RestoreSkeleton           shown while /api/auth/me resolves
    ├── LoginPage                 (currentPage === 'login', unauthenticated)
    └── TopNav + <main>
        ├── DashboardPage         upload → transcribe → results
        ├── HistoryPage    417 L  largest page: list, detail, delete
        └── SettingsPage   274 L  profile + note-style preferences
```

## Component hierarchy

```
components/layout/TopNav.tsx            nav + dark-mode + sign out

components/features/upload/
  UploadCard.tsx        encounter type + style override selection
  UploadZone.tsx  271 L drag/drop, file validation, duration probe (X-Audio-Duration-Seconds)
  TranscribeButton.tsx  submit + processing-status display

components/features/results/
  SessionView.tsx       composes the three result cards
  TranscriptCard.tsx    transcript + ASR confidence
  SoapCard.tsx          S/O/A/P sections, copy actions
  ContextCard.tsx 186 L entities, assertions, ontology codes, quality/verification
  EntityChip.tsx        one entity + its assertion/ontology badges

components/ui/          Button, Card, Badge, Field, Modal   (index.ts barrel)
lib/utils.ts            cn() + formatting helpers  ← gitignored once; keep tracked
```

## State — `store/appStore.ts` (Zustand, 250 L)

```
nav      currentPage, setPage
auth     isAuthenticated, authUser, setAuth, clearAuth
upload   selectedFile, uploadState, processingStatus, errorMessage,
         selectedEncounterType, styleOverridePreset,
         setFile/setUploadState/setProcessingStatus/setResult/setError
result   transcriptionResult
history  history[], setHistory
profile  UserProfile (incl. noteStylePreset, preferredFocus,
         includeBulletsInPlan, includePatientFriendlyLanguage)
prefs    autoScroll, compactView, showConfidence, autoCopy, darkMode
notifs   emailNotifs, transcriptDone, weeklyReport
```

Dark mode is token-driven: `App.tsx` toggles `.dark` on `<html>` and every
`--color-*` variable re-points. Components never branch on theme for colour.

## Data flow

```
UploadZone ─file─▶ store ─▶ TranscribeButton
     └─▶ api.transcribeAudio(FormData + X-Audio-Duration-Seconds)
              └─▶ POST /api/transcribe ─▶ setResult ─▶ SessionView

App mount ─▶ getStoredToken ─▶ fetchCurrentUser ─▶ setAuth
                            └─▶ fetchHistory ─▶ mapHistoryEntryFromApi ─▶ setHistory
HistoryPage ─▶ fetchTranscription(id) ─▶ mapHistoryDetailToResult ─▶ SessionView
```

## API layer — `services/api.ts` (357 L, sole network boundary)

```
token        getStoredToken / setStoredToken(remember) / clearStoredToken
interceptors attach Bearer; 401 → clearAuth, except on login/register routes
auth         loginUser, registerUser, fetchCurrentUser, updateCurrentUser, deleteMyAccount
history      fetchHistory, fetchTranscription, deleteHistoryItem, deleteAllHistory
mapping      mapHistoryEntryFromApi, mapHistoryDetailToResult, getUserStyleProfile
pipeline     transcribeAudio(file, encounterType, styleOverrides)
```

## Types — `types/index.ts`

`TranscriptionResult`, `HistoryEntry`, `EncounterType`, `NoteStylePreset`,
`NoteStyleProfile`, `UploadState`, `AppPage`.

## Build

```
npm run dev      vite            :5173
npm run build    tsc -b && vite build → frontend/dist
npm run lint     eslint (flat config, react-hooks + react-refresh)
deps             axios, zustand, lucide-react, sonner, clsx, tailwind-merge, cva
```
