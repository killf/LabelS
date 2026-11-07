import VideoAnnotator from '@labels/video-react';
import { forwardRef } from 'react';
import { MediaAnnotatorWrapper } from '@labels/audio-annotator-react';
import type { AudioAndVideoAnnotatorRef, AnnotatorProps } from '@labels/audio-annotator-react';

function ForwardAnnotator({ samples, ...props }: AnnotatorProps, ref: React.Ref<AudioAndVideoAnnotatorRef>) {
  return (
    <MediaAnnotatorWrapper samples={samples} ref={ref} {...props}>
      {(annotatorProps) => <VideoAnnotator {...annotatorProps} className="labels-video-wrapper" />}
    </MediaAnnotatorWrapper>
  );
}

export const Annotator = forwardRef<AudioAndVideoAnnotatorRef, AnnotatorProps>(ForwardAnnotator);
