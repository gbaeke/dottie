import '@/index.css'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router'
import { Toaster } from 'sonner'
import { RouteError } from '@/components/RouteError'
import { Shell } from '@/components/Shell'
import { setupApiClient } from '@/lib/api'
import { ThemeProvider } from '@/lib/theme'
import { Inbox } from '@/pages/Inbox'
import { NewDottie } from '@/pages/NewDottie'
import { NotFound } from '@/pages/NotFound'
import { Connect } from '@/pages/Connect'
import { Overview } from '@/pages/Overview'
import { Scheduled } from '@/pages/Scheduled'
import { Skills } from '@/pages/Skills'
import { Activity } from '@/pages/dottie/Activity'
import { Chat } from '@/pages/dottie/Chat'
import { DottieLayout } from '@/pages/dottie/DottieLayout'
import { Schedules } from '@/pages/dottie/Schedules'
import { DottieSettings } from '@/pages/dottie/Settings'
import { Wiki } from '@/pages/dottie/Wiki'

setupApiClient()
const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000 } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route element={<Shell />} errorElement={<RouteError />}>
              <Route index element={<Overview />} />
              <Route path="inbox" element={<Inbox />} />
              <Route path="scheduled" element={<Scheduled />} />
              <Route path="skills" element={<Skills />} />
              <Route path="connect" element={<Connect />} />
              <Route path="dotties/new" element={<NewDottie />} />
              <Route path="dotties/:id" element={<DottieLayout />}>
                <Route index element={<Chat />} />
                <Route path="c/:conversationId" element={<Chat />} />
                <Route path="wiki" element={<Wiki />} />
                <Route path="schedules" element={<Schedules />} />
                <Route path="activity" element={<Activity />} />
                <Route path="settings" element={<DottieSettings />} />
              </Route>
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster richColors />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
