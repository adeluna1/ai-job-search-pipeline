import ServiceEmbed from '@/components/ServiceEmbed';

export default function PaperclipPage() {
  return (
    <ServiceEmbed
      title="Paperclip"
      subtitle="multi-agent orchestrator (:3100)"
      service="paperclip"
      serviceKey="paperclip"
      url="http://127.0.0.1:3100"
      partition="persist:ee-paperclip"
    />
  );
}
