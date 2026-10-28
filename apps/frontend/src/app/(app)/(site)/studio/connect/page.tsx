export const dynamic = 'force-dynamic';
import { Metadata } from 'next';
import { Studio } from '@gitroom/frontend/components/studio/studio';

export const metadata: Metadata = {
  title: 'Postiz · Connexion Grok Bot',
};

export default function Page() {
  return <Studio key="studio-connection" connection />;
}
