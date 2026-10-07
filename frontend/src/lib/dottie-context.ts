import { useOutletContext } from 'react-router'
import type { DottieOut } from '@/client/types.gen'

/** The dottie whose page this is (provided by the dottie layout route). */
export const useDottie = () => useOutletContext<DottieOut>()
