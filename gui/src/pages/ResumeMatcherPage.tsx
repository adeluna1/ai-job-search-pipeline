import ServiceEmbed from '@/components/ServiceEmbed';

export default function ResumeMatcherPage() {
  return (
    <ServiceEmbed
      title="Resume-Matcher"
      subtitle="resume tailoring service (:3000, Docker)"
      service="resume-matcher"
      serviceKey="resumeMatcher"
      url="http://127.0.0.1:3000"
      partition="persist:ee-resume-matcher"
    />
  );
}
