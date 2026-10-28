export const dynamic = 'force-dynamic';
import { Metadata } from 'next';
import { Studio } from '@gitroom/frontend/components/studio/studio';

export const metadata: Metadata = {
  title: 'Postiz · Studio IA',
  description: 'Préparer les contenus, les campagnes et le blog de Planète Laser.',
};

export default function Page() {
  return <Studio />;
}
