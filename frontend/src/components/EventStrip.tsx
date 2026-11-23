import { type ReviewImage, imageUrl } from "../api/client";

interface Props {
  images: ReviewImage[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

export default function EventStrip({ images, activeIndex, onSelect }: Props) {
  if (images.length < 2) return null;
  return (
    <div className="event-strip">
      {images.map((img, i) => {
        const top = img.detections[0];
        return (
          <button
            key={img.id}
            type="button"
            className={`thumb${i === activeIndex ? " thumb-active" : ""}`}
            onClick={() => onSelect(i)}
            title={img.original_filename}
          >
            <img src={imageUrl(img.id)} alt="" loading="eager" />
            <span className="thumb-conf">{top ? top.confidence.toFixed(2) : "–"}</span>
          </button>
        );
      })}
    </div>
  );
}
