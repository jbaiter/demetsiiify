Vue.component('ManifestView', {
  props: ['manifest', 'width'],
  template: `
  <div class="column" :class="columnWidth">
    <div class="card manifest-view">
      <div class="card-content">
        <div class="media">
          <div class="media-left">
            <figure class="image manifest-preview">
              <a :href="viewerUrl" target="_blank">
                <img :src="manifest.thumbnail" alt="Preview">
              </a>
            </figure>
          </div>
          <div class="media-content">
            <p class="title is-5 manifest-label">{{ truncatedLabel }}</p>
            <p class="subtitle is-6">
              <img class="attribution-logo" :src="manifest.logo">
              <span v-html="manifest.attribution" />
            </p>
          </div>
        </div>
      </div>
      <div class="card-footer">
        <a class="card-footer-item" :href="manifest['@id']">
          <img src="/static/img/iiif_128.png" alt="IIIF Manifest">
        </a>
        <a v-if="manifest.metsurl" class="card-footer-item" :href="manifest.metsurl">
          <img src="/static/img/mets.png" alt="METS XML">
        </a>
        <a class="card-footer-item button is-primary" :href="viewerUrl"
           target="_blank">View</a>
      </div>
    </div>
  </div>`,
  computed: {
    columnWidth: function() {
      return `is-${this.width || 4}`;
    },
    viewerUrl: function() {
      return `/view/${this.manifest['@id'].split('/').slice(-2, 2)}`;
    },
    truncatedLabel: function() {
      if (this.manifest.label.length < 100) {
        return this.manifest.label;
      } else {
        var parts = this.manifest.label.split(" ");
        var label = "";
        while (label.length < 100) {
          var part = parts.shift();
          if ((label.length + part.length) > 100) {
            label += '…';
            break;
          }
          label += (" " + part);
        }
        return label;
      }
    }
  }
});
